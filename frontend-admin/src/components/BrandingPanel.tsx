import { Check, Loader2, Moon, Sun } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../services/api";
import {
  MIN_INK_CONTRAST,
  isValidHex,
  previewPalette,
  type PreviewPalette,
} from "../services/brandPalette";
import type { RestaurantTheme, ThemePreset } from "../types/app";

/**
 * Choosing the colour a restaurant's app is painted in.
 *
 * The preview is the point of the screen, so it derives its colours through the
 * same maths the device uses rather than approximating them in CSS. Both themes
 * are shown because a colour that reads well on white can be far too hot on a
 * near-black background - which is exactly how a muted green once shipped as
 * neon lime.
 */

const CUSTOM = "custom";

interface BrandingPanelProps {
  token: string;
  restaurantId: string;
  /** Shown until the theme request returns the restaurant's real name. */
  restaurantName: string;
  onToast: (title: string, description: string, tone?: "success" | "error" | "info") => void;
}

type PreviewScreen = "home" | "chat" | "cart";

const SCREENS: Array<{ id: PreviewScreen; label: string }> = [
  { id: "home", label: "Home" },
  { id: "chat", label: "Chat" },
  { id: "cart", label: "Cart" },
];

/**
 * The preview is built at the phone's real logical width and scaled down as a
 * whole, rather than at preview size with hand-shrunk numbers.
 *
 * Every measurement below is the value the app actually uses - a 44pt header
 * button, an 18pt bubble radius with its 4pt tail, a 58pt thumbnail, the 52pt
 * send button - taken from `mobile/src/screens/**` and `mobile/src/components/`.
 * Scaling one transform keeps all of that in proportion; guessing at reduced
 * numbers is what made the last version read as a mockup.
 */
const DEVICE_WIDTH = 393;

function StatusBar() {
  return (
    <div className="ph__status">
      <span>4:57</span>
      <span className="ph__island" />
      <span className="ph__signal" />
    </div>
  );
}

function TabBar({ active }: { active: PreviewScreen }) {
  const tabs: Array<{ id: string; label: string }> = [
    { id: "home", label: "Home" },
    { id: "orders", label: "Orders" },
    { id: "chat", label: "Chat" },
    { id: "profile", label: "Profile" },
  ];
  return (
    <div className="ph__tabbar">
      {tabs.map((tab) => (
        <span
          className={`ph__tab${tab.id === active ? " is-active" : ""}`}
          key={tab.id}
        >
          <i className="ph__tabicon" />
          {tab.label}
        </span>
      ))}
    </div>
  );
}

/** The sticky header: 44pt controls, a 48pt location card, a badged cart. */
function AppHeader({ name }: { name: string }) {
  return (
    <div className="ph__header">
      <span className="ph__profile">{name.slice(0, 1).toUpperCase()}</span>
      <span className="ph__loc">
        <b>Bhagal Cha…</b>
        <i>Stitching point</i>
        <em>⌄</em>
      </span>
      <span className="ph__iconbtn" />
      <span className="ph__iconbtn">
        <span className="ph__cartbadge">1</span>
      </span>
      <span className="ph__iconbtn" />
    </div>
  );
}

function HomeScreen({ name }: { name: string }) {
  return (
    <>
      <AppHeader name={name} />
      <div className="ph__scroll">
        <div className="ph__promo">
          <span className="ph__promo-top">
            <span className="ph__promo-icon" />
            <b>Not sure what to eat?</b>
          </span>
          <i>
            Ask AI for personalized recommendations based on your craving,
            budget, and mood.
          </i>
          <span className="ph__promo-row">
            <span className="ph__chip">Spicy</span>
            <span className="ph__chip">Under Rs. 250</span>
            <span className="ph__btn ph__btn--sm">Ask AI →</span>
          </span>
        </div>

        <div className="ph__sec">
          <span className="ph__sec-copy">
            <b>Personalized Picks</b>
            <i>Fresh matches ranked for your tastes.</i>
          </span>
          <span className="ph__seeall">See all</span>
        </div>

        <div className="ph__pick">
          <div className="ph__pick-media">
            <span className="ph__match">37% Match</span>
            <span className="ph__heart" />
          </div>
          <div className="ph__pick-body">
            <span className="ph__pick-title">
              <i className="ph__veg" />
              Thai Basil Chicken
            </span>
            <span className="ph__pick-tags">
              <span className="ph__chip">Main Course</span>
              <span className="ph__chip is-brand">Recommended for You</span>
            </span>
            <span className="ph__pick-meta">
              {name} · Nearest: {name} Bodakdev
            </span>
            <span className="ph__rule" />
            <span className="ph__pick-foot">
              <span className="ph__price">
                <em>FROM</em>
                <b>₹14.49</b>
              </span>
              <span className="ph__chip is-brand">3 Branches</span>
              <span className="ph__btn">+ Add</span>
            </span>
          </div>
        </div>

        <div className="ph__sec">
          <span className="ph__sec-copy">
            <b>Frequently Ordered Together</b>
            <i>Auto-generated bundles built from real completed orders.</i>
          </span>
        </div>

        <div className="ph__combo">
          <span className="ph__combo-top">
            <span className="ph__chip is-brand">🔥 Trending</span>
            <span className="ph__heart" />
          </span>
          <b>Thai Iced Tea + Red Curry Tofu Combo</b>
          <span className="ph__combo-meta">
            <span className="ph__chip">{name}</span>
            <span className="ph__chip is-brand">6+ ordered</span>
          </span>
          <span className="ph__combo-foot">
            <span className="ph__accent">₹16.45</span>
            <s>₹18.08</s>
            <span className="ph__round">+</span>
          </span>
        </div>
      </div>
      <TabBar active="home" />
    </>
  );
}

function ChatScreen({ name }: { name: string }) {
  return (
    <>
      <div className="ph__scroll ph__scroll--chat">
        <div className="ph__chathead">
          <span className="ph__chip is-brand">AI Concierge</span>
          <span className="ph__ghost">🗑 Clear chat</span>
        </div>
        <b className="ph__h1">Tell me your craving.</b>
        <i className="ph__lead">
          I can suggest dishes by budget, spice level, meal mood, or group size.
        </i>

        <div className="ph__row ph__row--me">
          <span className="ph__bubble ph__bubble--me">
            what can i get under 10 ruppee
          </span>
        </div>

        <div className="ph__row">
          <span className="ph__avatar">AI</span>
          <span className="ph__bubble">
            Looking for something under 10 rupees? The Thai Iced Tea is a great
            pick — it’s a refreshing, sweet drink ☕.
            <span className="ph__food">
              <span className="ph__foodimg" />
              <span className="ph__foodcopy">
                <b>Thai Iced Tea</b>
                <i>{name}</i>
                <i>₹4.39</i>
              </span>
              <span className="ph__btn ph__btn--add">+ ADD</span>
            </span>
            <span className="ph__food">
              <span className="ph__foodimg" />
              <span className="ph__foodcopy">
                <b>Coconut Pandan Pudding</b>
                <i>{name}</i>
                <i>₹5.99</i>
              </span>
              <span className="ph__btn ph__btn--add">+ ADD</span>
            </span>
          </span>
        </div>
      </div>

      <div className="ph__composer">
        <span className="ph__input">Type your question...</span>
        <span className="ph__send">➤</span>
      </div>
      <TabBar active="chat" />
    </>
  );
}

/** Cart is a stack screen: a back-and-title bar, no tab bar, a sticky pay bar. */
function CartScreen() {
  return (
    <>
      <div className="ph__navbar">
        <span className="ph__back">←</span>
        <b>Cart</b>
      </div>
      <div className="ph__scroll">
        <div className="ph__panel">
          <span className="ph__panel-head">
            <span className="ph__sec-copy">
              <b>Your items</b>
              <i>Review quantities before checkout</i>
            </span>
            <span className="ph__count">7</span>
          </span>

          <div className="ph__item">
            <span className="ph__itemimg" />
            <span className="ph__itemcopy">
              <b>Thai Basil Chicken</b>
              <i>Main Course</i>
              <span className="ph__itemprice">
                <span className="ph__pricestack">
                  <em>EACH</em>
                  <i>₹14.84</i>
                </span>
                <b>₹103.88</b>
              </span>
            </span>
            <span className="ph__qty">
              <em>−</em>
              <span>7</span>
              <em>+</em>
            </span>
          </div>

          <span className="ph__addmore">
            <span className="ph__addmore-copy">
              <b>⊕ Add more items</b>
              <i>Browse more from this restaurant</i>
            </span>
            <i className="ph__chev">›</i>
          </span>
        </div>

        <div className="ph__panel ph__panel--plain">
          <span className="ph__sec-copy">
            <b>Order details</b>
            <i>Add kitchen or rider instructions</i>
          </span>
          <i className="ph__chev">⌄</i>
        </div>

        <div className="ph__bill">
          <span className="ph__bill-head">
            <span className="ph__sec-copy">
              <b>Bill details</b>
              <i>A clean breakdown before you pay</i>
            </span>
            <span className="ph__accent">Live total</span>
          </span>
          <span className="ph__bill-row">
            <i>Fulfillment</i>
            <b>Pickup · ASAP · 19 mins</b>
          </span>
          <span className="ph__bill-row">
            <i>Subtotal</i>
            <b>₹103.88</b>
          </span>
          <span className="ph__bill-row">
            <i>Delivery fee</i>
            <b>₹0.00</b>
          </span>
          <span className="ph__bill-row">
            <i>Tax</i>
            <b>₹5.19</b>
          </span>
          <span className="ph__rule" />
          <span className="ph__bill-row is-total">
            <b>Total</b>
            <b>₹109.07</b>
          </span>
        </div>
      </div>

      <div className="ph__paybar">
        <span className="ph__pay">
          <em>TO PAY</em>
          <b>₹109.07</b>
          <i>7 items · Pickup · ASAP</i>
        </span>
        <span className="ph__btn ph__btn--pay">Continue to payment</span>
      </div>
    </>
  );
}

/** One phone, painted with a resolved palette. */
function PhonePreview({
  palette,
  restaurantName,
  screen,
}: {
  palette: PreviewPalette;
  restaurantName: string;
  screen: PreviewScreen;
}) {
  const style = {
    "--p": palette.primary,
    "--on-p": palette.onPrimary,
    "--soft": palette.primarySoft,
    "--hero": palette.hero,
    "--alt": palette.surfaceAlt,
    "--raised": palette.surfaceRaised,
    "--chip": palette.chip,
    "--bg": palette.background,
    "--card": palette.card,
    "--line": palette.border,
    "--muted": palette.muted,
    "--hint": palette.hint,
    "--ink": palette.text,
    "--ink-2": palette.secondaryText,
    "--tab": palette.tabBar,
    "--w": `${DEVICE_WIDTH}px`,
  } as React.CSSProperties;

  return (
    <div className="ph__stage">
      <div className={`ph ph--${palette.mode}`} style={style}>
        <StatusBar />
        {screen === "home" ? <HomeScreen name={restaurantName} /> : null}
        {screen === "chat" ? <ChatScreen name={restaurantName} /> : null}
        {screen === "cart" ? <CartScreen /> : null}
      </div>
    </div>
  );
}

export function BrandingPanel({
  token,
  restaurantId,
  restaurantName,
  onToast,
}: BrandingPanelProps) {
  const [theme, setTheme] = useState<RestaurantTheme | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>(CUSTOM);
  const [custom, setCustom] = useState("#FF5200");
  const [mode, setMode] = useState<"light" | "dark">("light");
  const [screen, setScreen] = useState<PreviewScreen>("home");

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoading(true);
      try {
        const result = await api.getRestaurantTheme(token, restaurantId);
        if (!active) return;
        setTheme(result);
        setSelected(result.preset);
        setCustom(result.primary_color);
        setError(null);
      } catch (caught) {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : "Unable to load the theme.");
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [token, restaurantId]);

  const activeColor = useMemo(() => {
    if (selected !== CUSTOM) {
      const preset = theme?.presets.find((row) => row.id === selected);
      if (preset) return preset.primary_color;
    }
    return isValidHex(custom) ? custom.toUpperCase() : "#FF5200";
  }, [selected, custom, theme]);

  // Both are computed every render so switching themes is instant and the
  // warning below can speak about the mode the owner is not looking at.
  const light = useMemo(() => previewPalette(activeColor, "light"), [activeColor]);
  const dark = useMemo(() => previewPalette(activeColor, "dark"), [activeColor]);
  const shown = mode === "dark" ? dark : light;

  const customValid = isValidHex(custom);
  const weakMode =
    light.inkContrast < MIN_INK_CONTRAST
      ? "light"
      : dark.inkContrast < MIN_INK_CONTRAST
        ? "dark"
        : null;
  const dirty = theme !== null && (selected !== theme.preset || activeColor !== theme.primary_color);
  const displayName = theme?.restaurant_name || restaurantName;

  const save = async () => {
    if (saving || !theme) return;
    if (selected === CUSTOM && !customValid) {
      onToast("Check the colour", "Use a six-digit hex value such as #FF5200.", "error");
      return;
    }
    setSaving(true);
    try {
      const result = await api.updateRestaurantTheme(token, restaurantId, {
        preset: selected,
        primary_color: selected === CUSTOM ? custom.toUpperCase() : null,
      });
      setTheme(result);
      setSelected(result.preset);
      setCustom(result.primary_color);
      onToast("Theme applied", "Customers will see it the next time the app starts.", "success");
    } catch (caught) {
      onToast(
        "Theme not saved",
        caught instanceof ApiError ? caught.message : "Please try again.",
        "error",
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="hint-text">Loading branding…</p>;
  }
  if (error || !theme) {
    return <p className="field__error">{error ?? "Unable to load the theme."}</p>;
  }

  return (
    <div className="bp">
      <div className="bp__picker">
        <div className="bp__section">
          <div className="bp__section-head">
            <h3>Choose a colour</h3>
            <p>
              Every colour here has been checked in both light and dark themes, so
              labels stay legible whichever your customers use.
            </p>
          </div>

          <div className="bp__swatches" role="radiogroup" aria-label="Brand colour presets">
            {theme.presets.map((preset: ThemePreset) => {
              const active = selected === preset.id;
              return (
                <button
                  aria-checked={active}
                  className={`bp-swatch${active ? " is-active" : ""}`}
                  key={preset.id}
                  onClick={() => {
                    setSelected(preset.id);
                    setCustom(preset.primary_color);
                  }}
                  role="radio"
                  title={preset.description}
                  type="button"
                >
                  <span
                    className="bp-swatch__chip"
                    style={{ background: preset.primary_color }}
                  >
                    {active ? <Check size={15} strokeWidth={3.2} /> : null}
                  </span>
                  <span className="bp-swatch__name">{preset.label}</span>
                  <span className="bp-swatch__hex">{preset.primary_color}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="bp__section">
          <div className="bp__section-head">
            <h3>Or use your own</h3>
            <p>For a brand that is one specific colour and nothing else.</p>
          </div>
          {/* Built to match a swatch tile rather than sit beside them as a bare
              pair of inputs: it is the thirteenth option, not a separate form. */}
          <label
            className={`bp__custom${selected === CUSTOM ? " is-active" : ""}`}
          >
            <span className="bp__custom-swatch">
              <input
                aria-label="Pick a custom brand colour"
                onChange={(event) => {
                  setSelected(CUSTOM);
                  setCustom(event.target.value.toUpperCase());
                }}
                type="color"
                value={customValid ? custom : "#FF5200"}
              />
            </span>
            <span className="bp__custom-fields">
              <b>Custom colour</b>
              <input
                aria-label="Custom brand colour hex value"
                className={customValid || !custom ? undefined : "is-invalid"}
                maxLength={7}
                onChange={(event) => {
                  setSelected(CUSTOM);
                  setCustom(event.target.value.toUpperCase());
                }}
                placeholder="#FF5200"
                type="text"
                value={custom}
              />
            </span>
            {selected === CUSTOM && customValid ? (
              <span className="bp__custom-tag">In use</span>
            ) : null}
          </label>
          {!customValid && custom ? (
            <p className="field__error">Use a six-digit hex value, e.g. #FF5200.</p>
          ) : weakMode ? (
            // Never a block: some brands genuinely are pale, and the app falls
            // back to dark label text. The owner should know that will happen.
            <p className="bp__warning">
              In the {weakMode} theme white button text is hard to read on this
              colour, so the app will use dark text instead.
            </p>
          ) : null}
        </div>

      </div>

      <aside className="bp__preview">
        <div className="bp__preview-head">
          <span className="bp__preview-label">Live preview</span>
          <div className="bp__modes" role="group" aria-label="Preview theme">
            <button
              aria-pressed={mode === "light"}
              className={mode === "light" ? "is-active" : undefined}
              onClick={() => setMode("light")}
              type="button"
            >
              <Sun size={13} strokeWidth={2.3} />
              Light
            </button>
            <button
              aria-pressed={mode === "dark"}
              className={mode === "dark" ? "is-active" : undefined}
              onClick={() => setMode("dark")}
              type="button"
            >
              <Moon size={13} strokeWidth={2.3} />
              Dark
            </button>
          </div>
        </div>

        {/* Three screens rather than one: the accent does different jobs on
            each - a filled pay button, a chat bubble, a tinted bill - and a
            colour that works on the home screen can still be wrong on them. */}
        <div className="bp__screens" role="tablist" aria-label="Preview screen">
          {SCREENS.map((row) => (
            <button
              aria-selected={screen === row.id}
              className={screen === row.id ? "is-active" : undefined}
              key={row.id}
              onClick={() => setScreen(row.id)}
              role="tab"
              type="button"
            >
              {row.label}
            </button>
          ))}
        </div>

        <PhonePreview palette={shown} restaurantName={displayName} screen={screen} />

        <dl className="bp__facts">
          <div>
            <dt>Accent</dt>
            <dd>{shown.primary}</dd>
          </div>
          <div>
            <dt>Button text</dt>
            <dd>{shown.inkContrast.toFixed(1)}:1</dd>
          </div>
        </dl>
        <p className="bp__note">
          Dark mode lifts the accent so it stays visible, keeping your colour’s
          own depth.
        </p>
      </aside>

      {/* Spans the card and sits on a rule, so the action anchors the panel
          instead of floating in the middle of an empty column. */}
      <div className="bp__actions">
        <span className="bp__live">
          <span
            className="bp__live-dot"
            style={{ background: theme.primary_color }}
          />
          <span className="bp__live-copy">
            <b>
              {dirty
                ? "Unsaved changes"
                : `Live: ${theme.presets.find((p) => p.id === theme.preset)?.label ?? "Custom"}`}
            </b>
            <i>
              {dirty
                ? `${activeColor} is not applied yet`
                : `${theme.primary_color} · applied to your app`}
            </i>
          </span>
        </span>
        <button
          className="primary-button"
          disabled={saving || !dirty}
          onClick={() => void save()}
          type="button"
        >
          {saving ? <Loader2 className="bp__spin" size={15} /> : null}
          {saving ? "Applying…" : "Apply theme"}
        </button>
      </div>
    </div>
  );
}
