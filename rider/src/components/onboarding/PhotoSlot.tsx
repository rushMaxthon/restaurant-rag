import React, { useEffect, useRef, useState } from 'react';
import {
  Image,
  PermissionsAndroid,
  Platform,
  StyleSheet,
  View,
} from 'react-native';
import Animated, { FadeIn } from 'react-native-reanimated';
import {
  launchCamera,
  launchImageLibrary,
  type CameraOptions,
  type ImagePickerResponse,
} from 'react-native-image-picker';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Icon } from '@components/ui/Icon';
import { Pill } from '@components/ui/Pill';
import { useI18n } from '@/i18n';
import { ApiError } from '@/services/http';
import { useApi } from '@/store/SessionProvider';
import type { ApplicationView, PhotoKind, UploadFile } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { haptic } from '@utils/haptics';
import { itemState } from '@utils/onboarding';

/**
 * Photos leave the phone at up to 1600 px and JPEG 0.8 - typically under
 * 1 MB, well inside the server's limit, and quick on a slow cell. The picker
 * does the resizing, so a 50 MP camera never uploads 12 MB.
 */
const PICK: CameraOptions = {
  mediaType: 'photo',
  maxWidth: 1600,
  maxHeight: 1600,
  quality: 0.8,
  includeBase64: false,
  saveToPhotos: false,
};

type Phase = 'idle' | 'uploading' | 'done' | 'failed';

/** Declaring CAMERA in the manifest makes the picker refuse until the rider allows it at runtime. */
async function cameraAllowed(): Promise<boolean> {
  if (Platform.OS !== 'android') return true;
  const result = await PermissionsAndroid.request(
    PermissionsAndroid.PERMISSIONS.CAMERA,
  );
  return result === PermissionsAndroid.RESULTS.GRANTED;
}

/**
 * One document photo: a frame guide until there is a picture, then the
 * picture with its upload progress. A failed upload KEEPS the photo and
 * offers Retry - on a bad network the rider should not have to find the
 * card and photograph it again. Sends as soon as it is taken: Android's
 * camera already asked "use this photo?", a second ask would be noise.
 *
 * The server never sends a photo back (it holds IDs); a photo given on an
 * earlier visit shows as "Photo added".
 */
export function PhotoSlot({
  kind,
  title,
  hint,
  view,
  face = false,
  onUploaded,
  onBusy,
  error,
}: {
  kind: PhotoKind;
  title: string;
  hint?: string;
  view: ApplicationView;
  /** The selfie: a round guide, the front camera, and no gallery. */
  face?: boolean;
  onUploaded: (view: ApplicationView) => void;
  onBusy: (kind: PhotoKind, busy: boolean) => void;
  /** From the step: "Add this photo" when Next was pressed without it. */
  error?: string | null;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const api = useApi();
  const item = view.items.find(i => i.kind === kind);
  const editable = item?.editable ?? false;
  const [file, setFile] = useState<UploadFile | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [pct, setPct] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );

  const send = async (next: UploadFile) => {
    setPhase('uploading');
    setPct(0);
    setProblem(null);
    onBusy(kind, true);
    try {
      const updated = await api.uploadPhoto(
        kind,
        next,
        fraction => alive.current && setPct(Math.round(fraction * 100)),
      );
      if (!alive.current) return;
      setPhase('done');
      haptic('success');
      onUploaded(updated);
    } catch (e) {
      if (!alive.current) return;
      setPhase('failed');
      haptic('error');
      setProblem(
        e instanceof ApiError ? e.message : t('onboarding.photo.failed'),
      );
    } finally {
      onBusy(kind, false);
    }
  };

  const pick = async (camera: boolean) => {
    setProblem(null);
    if (camera && !(await cameraAllowed())) {
      setProblem(t('onboarding.photo.cameraDenied'));
      return;
    }
    let result: ImagePickerResponse;
    try {
      result = camera
        ? await launchCamera({ ...PICK, cameraType: face ? 'front' : 'back' })
        : await launchImageLibrary({ ...PICK, selectionLimit: 1 });
    } catch {
      setProblem(t('onboarding.photo.cameraMissing'));
      return;
    }
    if (result.didCancel) return;
    if (result.errorCode) {
      setProblem(
        result.errorCode === 'permission'
          ? t('onboarding.photo.cameraDenied')
          : result.errorCode === 'camera_unavailable'
          ? t('onboarding.photo.cameraMissing')
          : result.errorMessage ?? t('onboarding.photo.failed'),
      );
      return;
    }
    const asset = result.assets?.[0];
    if (!asset?.uri) return;
    const next = {
      uri: asset.uri,
      type: asset.type ?? 'image/jpeg',
      name: asset.fileName ?? `${kind.toLowerCase()}.jpg`,
    };
    setFile(next);
    void send(next);
  };

  const state =
    phase === 'done'
      ? view.status === 'DRAFT'
        ? 'added'
        : 'inReview'
      : itemState(view, kind);
  const flagged = item?.status === 'NEEDS_CHANGE' && phase !== 'done';
  const hasPhoto = Boolean(file) || Boolean(item?.has_photo);
  const message = problem ?? error ?? null;
  const border = flagged || message ? colors.danger : colors.border;

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: colors.surface, borderColor: border },
      ]}
    >
      <View style={styles.head}>
        <AppText variant="bodyStrong" style={styles.flex}>
          {title}
        </AppText>
        {state !== 'todo' ? (
          <Pill
            label={t(`onboarding.state.${state}`)}
            tone={
              state === 'fix'
                ? 'danger'
                : state === 'accepted'
                ? 'success'
                : 'primary'
            }
          />
        ) : null}
      </View>
      {hint ? (
        <AppText variant="caption" tone="muted">
          {hint}
        </AppText>
      ) : null}

      <View
        style={[
          styles.frame,
          face ? styles.faceFrame : styles.docFrame,
          { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
        ]}
      >
        {file ? (
          <Image
            source={{ uri: file.uri }}
            style={styles.fill}
            resizeMode="cover"
            accessibilityIgnoresInvertColors
          />
        ) : hasPhoto ? (
          <View style={styles.center}>
            <View
              style={[styles.badge, { backgroundColor: colors.successSoft }]}
            >
              <Icon name="checkmark" size={26} color={colors.success} />
            </View>
            <AppText variant="label" tone="muted">
              {t('onboarding.photo.onFile')}
            </AppText>
          </View>
        ) : (
          <View style={styles.center}>
            <View
              style={[
                face ? styles.faceGuide : styles.docGuide,
                { borderColor: flagged ? colors.danger : colors.textFaint },
              ]}
            >
              <Icon
                name={face ? 'person-outline' : 'id-card-outline'}
                size={34}
                color={colors.textFaint}
              />
            </View>
            <AppText variant="caption" tone="faint" align="center">
              {face
                ? t('onboarding.photo.selfieFrame')
                : t('onboarding.photo.frameHint')}
            </AppText>
          </View>
        )}

        {phase === 'uploading' ? (
          <Animated.View
            entering={FadeIn}
            style={[styles.status, { backgroundColor: colors.overlay }]}
          >
            <AppText variant="label" style={styles.light}>
              {t('onboarding.photo.uploading', { pct })}
            </AppText>
            <View style={styles.track}>
              <View
                style={[
                  styles.bar,
                  { width: `${pct}%`, backgroundColor: colors.primary },
                ]}
              />
            </View>
          </Animated.View>
        ) : phase === 'done' ? (
          <Animated.View
            entering={FadeIn}
            style={[
              styles.status,
              styles.statusRow,
              { backgroundColor: colors.overlay },
            ]}
          >
            <Icon name="cloud-done-outline" size={18} color={colors.success} />
            <AppText variant="label" style={styles.light}>
              {t('onboarding.photo.uploaded')}
            </AppText>
          </Animated.View>
        ) : phase === 'failed' ? (
          <Animated.View
            entering={FadeIn}
            style={[
              styles.status,
              styles.statusRow,
              { backgroundColor: colors.overlay },
            ]}
          >
            <Icon
              name="cloud-offline-outline"
              size={18}
              color={colors.danger}
            />
            <AppText variant="label" style={styles.light}>
              {t('onboarding.photo.failed')}
            </AppText>
          </Animated.View>
        ) : null}
      </View>

      {flagged && item?.reason ? (
        <View style={styles.reason}>
          <Icon name="alert-circle" size={18} color={colors.danger} />
          <AppText variant="label" tone="danger" style={styles.flex}>
            {item.reason}
          </AppText>
        </View>
      ) : null}
      {message ? (
        <AppText variant="caption" tone="danger">
          {message}
        </AppText>
      ) : null}

      {editable ? (
        <View style={styles.actions}>
          {phase === 'failed' && file ? (
            <>
              <Button
                style={styles.flex}
                size="md"
                icon="refresh"
                label={t('onboarding.photo.retry')}
                onPress={() => void send(file)}
              />
              <Button
                style={styles.flex}
                size="md"
                kind="secondary"
                icon="camera-outline"
                label={t('onboarding.photo.retake')}
                onPress={() => void pick(true)}
              />
            </>
          ) : (
            <>
              <Button
                style={styles.flex}
                size="md"
                kind={hasPhoto ? 'secondary' : 'primary'}
                icon="camera-outline"
                label={
                  hasPhoto
                    ? t('onboarding.photo.retake')
                    : t('onboarding.photo.take')
                }
                loading={phase === 'uploading'}
                onPress={() => void pick(true)}
              />
              {face ? null : (
                <Button
                  style={styles.flex}
                  size="md"
                  kind="secondary"
                  icon="images-outline"
                  label={t('onboarding.photo.gallery')}
                  onPress={() => phase !== 'uploading' && void pick(false)}
                />
              )}
            </>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.xl,
    borderWidth: 1,
    padding: space.lg,
    gap: space.sm,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  flex: { flex: 1 },
  frame: {
    borderRadius: radius.lg,
    borderWidth: 1,
    overflow: 'hidden',
    marginTop: space.xs,
  },
  // An ID card is 85.6 x 54 mm; the frame matches so "fit it inside" means something.
  docFrame: { aspectRatio: 1.58 },
  faceFrame: {
    aspectRatio: 1,
    maxHeight: 280,
    alignSelf: 'center',
    width: '100%',
  },
  fill: { width: '100%', height: '100%' },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
    padding: space.md,
  },
  docGuide: {
    width: '78%',
    aspectRatio: 1.58,
    maxHeight: '72%',
    borderWidth: 2,
    borderStyle: 'dashed',
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  faceGuide: {
    width: '52%',
    aspectRatio: 0.8,
    borderWidth: 2,
    borderStyle: 'dashed',
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badge: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
  },
  status: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    gap: space.xs,
  },
  statusRow: { flexDirection: 'row', alignItems: 'center' },
  // Over the dark overlay in both themes.
  light: { color: '#FFFFFF' },
  track: {
    height: 4,
    borderRadius: 2,
    backgroundColor: 'rgba(255,255,255,0.25)',
    overflow: 'hidden',
  },
  bar: { height: '100%' },
  reason: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-start' },
  actions: { flexDirection: 'row', gap: space.sm, marginTop: space.xs },
});
