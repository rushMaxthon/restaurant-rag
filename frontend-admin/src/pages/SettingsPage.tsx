import { LogOut, Shield, Store } from "lucide-react";
import { useState, type ReactNode } from "react";
import { PageIntro } from "../components/PageIntro";
import { useAdminStore } from "../hooks/useAdminStore";
import { clearPageSnapshots, countPageSnapshots } from "../services/pageCache";
import {
  DEFAULT_WORKSPACE_SETTINGS,
  PAGE_SIZE_CHOICES,
  PERIOD_CHOICES,
  clearWorkspaceSettings,
  readWorkspaceSettings,
  writeWorkspaceSettings,
  WORKSPACE_SETTINGS_KEY,
  type WorkspaceSettings,
} from "../services/workspaceSettings";

interface SettingsPageProps {
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

const PERIOD_LABEL: Record<number, string> = {
  7: "7 days",
  30: "30 days",
  90: "3 months",
};

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "?";
  }
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1][0] ?? "") : "";
  return `${first}${last}`.toUpperCase();
}

function formatJoined(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** A read-only fact in the rail. Label left, value right, hairline between. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="set-fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function RailCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="set-rail__card">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

/**
 * One setting: what it is on the left, the control on the right.
 *
 * No icon and no border of its own. The previous version nested a bordered row
 * inside a bordered card inside a bordered page section - three frames around a
 * single switch - and gave every row a decorative glyph that carried nothing.
 */
function Setting({
  label,
  description,
  children,
}: {
  label: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="set-item">
      <div className="set-item__copy">
        <strong>{label}</strong>
        <span>{description}</span>
      </div>
      <div className="set-item__control">{children}</div>
    </div>
  );
}

function Group({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="set-group">
      <header className="set-group__head">
        <h2>{title}</h2>
        {note ? <p>{note}</p> : null}
      </header>
      <div className="set-group__items">{children}</div>
    </section>
  );
}

function Switch({
  on,
  onToggle,
  label,
}: {
  on: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button
      aria-label={label}
      aria-pressed={on}
      className={on ? "st-switch st-switch--on" : "st-switch"}
      onClick={onToggle}
      type="button"
    >
      <span className="st-switch__thumb" />
    </button>
  );
}

function Choice<T extends number>({
  value,
  options,
  format,
  onSelect,
  label,
}: {
  value: T;
  options: readonly T[];
  format: (option: T) => string;
  onSelect: (option: T) => void;
  label: string;
}) {
  return (
    <span aria-label={label} className="set-choice" role="group">
      {options.map((option) => (
        <button
          aria-pressed={value === option}
          className={`set-choice__option${value === option ? " is-active" : ""}`}
          key={option}
          onClick={() => onSelect(option)}
          type="button"
        >
          {format(option)}
        </button>
      ))}
    </span>
  );
}

export function SettingsPage({ onToast }: SettingsPageProps) {
  const { user, role, logout } = useAdminStore();
  const [settings, setSettings] = useState<WorkspaceSettings>(() =>
    readWorkspaceSettings(),
  );
  /* Both counts are read once on mount and again after the action that changes
     them, so the two buttons in Reset show what they are about to act on. */
  const [cachedScreens, setCachedScreens] = useState(() =>
    countPageSnapshots(),
  );
  const [customised, setCustomised] = useState(
    () => window.localStorage.getItem(WORKSPACE_SETTINGS_KEY) !== null,
  );

  const save = (next: WorkspaceSettings, note: string) => {
    setSettings(next);
    writeWorkspaceSettings(next);
    setCustomised(true);
    onToast("Preference saved", note, "success");
  };

  const isAdmin = role === "ADMIN";

  return (
    <div className="page-stack">
      <PageIntro
        description="Your account and the preferences stored in this browser."
        eyebrow="System"
        title="Settings"
      />

      <div className="set-shell">
        <div className="set-sheet">
          {/* The account is a strip, not a card. It is four read-only facts and a
            sign-out; framing it like a settings panel overstated it. */}
          {user ? (
            <header className="set-identity">
              <span
                className={`st-avatar st-avatar--${(role ?? "ADMIN").toLowerCase()}`}
              >
                {getInitials(user.full_name)}
              </span>
              <div className="set-identity__copy">
                <strong>{user.full_name}</strong>
                <span>{user.email}</span>
              </div>
              <span
                className={`st-role-pill st-role-pill--${(role ?? "ADMIN").toLowerCase()}`}
              >
                {isAdmin ? (
                  <Shield size={12} strokeWidth={2.2} />
                ) : (
                  <Store size={12} strokeWidth={2.2} />
                )}
                {isAdmin ? "Platform Admin" : "Restaurant Owner"}
              </span>
              <button
                className="secondary-button"
                onClick={logout}
                type="button"
              >
                <LogOut size={15} strokeWidth={2.1} />
                Sign out
              </button>
            </header>
          ) : null}

          <p className="set-scope">
            {isAdmin
              ? "This account can see every restaurant, user, and report on the platform."
              : "This account can see your assigned restaurant and its branches."}
          </p>

          <Group
            note="How much fits on screen at once. Saved in this browser."
            title="Appearance"
          >
            <Setting
              description="Tightens padding and row height across every screen."
              label="Compact density"
            >
              <Switch
                label="Compact density"
                on={settings.compactDashboard}
                onToggle={() =>
                  save(
                    {
                      ...settings,
                      compactDashboard: !settings.compactDashboard,
                    },
                    "Applies across the console.",
                  )
                }
              />
            </Setting>
          </Group>

          <Group
            note="What screens start with, before you change them."
            title="Defaults"
          >
            <Setting
              description="The window the AI Manager opens on."
              label="Reporting period"
            >
              <Choice
                format={(days) => PERIOD_LABEL[days] ?? `${days} days`}
                label="Reporting period"
                onSelect={(days) =>
                  save(
                    { ...settings, defaultPeriodDays: days },
                    "The AI Manager will open on this window.",
                  )
                }
                options={PERIOD_CHOICES}
                value={settings.defaultPeriodDays}
              />
            </Setting>
            <Setting
              description="How many rows every table starts with."
              label="Rows per page"
            >
              <Choice
                format={(size) => String(size)}
                label="Rows per page"
                onSelect={(size) =>
                  save(
                    { ...settings, defaultPageSize: size },
                    "Tables will start with this many rows.",
                  )
                }
                options={PAGE_SIZE_CHOICES}
                value={settings.defaultPageSize}
              />
            </Setting>
          </Group>

          {/* Authority, not screen space: a maintenance notice is a platform-wide
            announcement, and an owner has no platform to announce to. */}
          {isAdmin ? (
            <Group note="Visible to platform admins only." title="Platform">
              <Setting
                description="Pins a maintenance notice above every screen. This browser only, so it will not warn your team."
                label="Maintenance banner"
              >
                <Switch
                  label="Maintenance banner"
                  on={settings.maintenanceBanner}
                  onToggle={() =>
                    save(
                      {
                        ...settings,
                        maintenanceBanner: !settings.maintenanceBanner,
                      },
                      "Applies in this browser.",
                    )
                  }
                />
              </Setting>
            </Group>
          ) : null}

          <Group
            note="Neither affects your account or any stored data."
            title="Reset"
          >
            <Setting
              description={
                cachedScreens === 0
                  ? "Nothing is cached right now. Screens will fetch fresh anyway."
                  : `${cachedScreens} ${cachedScreens === 1 ? "screen holds" : "screens hold"} a snapshot so going back does not refetch. This forces a fresh pull.`
              }
              label="Cached data"
            >
              <button
                className="secondary-button"
                onClick={() => {
                  clearPageSnapshots();
                  setCachedScreens(countPageSnapshots());
                  onToast(
                    "Cached data cleared",
                    "Screens will refetch on their next visit.",
                    "info",
                  );
                }}
                type="button"
              >
                Clear cache
              </button>
            </Setting>
            <Setting
              description={
                customised
                  ? "Returns every preference above to its default."
                  : "Everything above is already at its default."
              }
              label="Preferences"
            >
              <button
                className="secondary-button"
                onClick={() => {
                  clearWorkspaceSettings();
                  setSettings(DEFAULT_WORKSPACE_SETTINGS);
                  setCustomised(false);
                  onToast(
                    "Preferences reset",
                    "Restored to their defaults.",
                    "info",
                  );
                }}
                type="button"
              >
                Reset all
              </button>
            </Setting>
          </Group>
        </div>

        {/* The sheet is capped so a switch never floats a screen-width away from
          its label. The rail spends the leftover width on the facts the sheet
          deliberately does not carry: read-only account detail, what this
          browser is actually holding, and the two real shortcuts. */}
        <aside className="set-rail">
          {user ? (
            <RailCard title="Account">
              <dl className="set-facts">
                {!isAdmin && user.restaurant_name ? (
                  <Fact label="Restaurant">{user.restaurant_name}</Fact>
                ) : null}
                <Fact label="Phone">{user.phone_number ?? "Not set"}</Fact>
                <Fact label="Email">
                  {user.is_verified ? "Verified" : "Unverified"}
                </Fact>
                <Fact label="Status">
                  {user.is_active ? "Active" : "Suspended"}
                </Fact>
                <Fact label="Joined">{formatJoined(user.created_at)}</Fact>
              </dl>
            </RailCard>
          ) : null}

          <RailCard title="This browser">
            <dl className="set-facts">
              <Fact label="Cached screens">{cachedScreens}</Fact>
              <Fact label="Preferences">
                {customised ? "Customised" : "Default"}
              </Fact>
            </dl>
            <p className="set-rail__note">
              Nothing here leaves this browser. Signing out on another device
              does not change it.
            </p>
          </RailCard>

          <RailCard title="Shortcuts">
            <dl className="set-facts">
              <Fact label={"\u2318K / Ctrl+K"}>Ask your data</Fact>
              <Fact label="Esc">Close a dialog</Fact>
            </dl>
            <p className="set-rail__note">
              {"\u2318K works on the AI Manager screen."}
            </p>
          </RailCard>
        </aside>
      </div>
    </div>
  );
}
