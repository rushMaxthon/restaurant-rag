import { useEffect, useState } from 'react';
import { Database, FlaskConical } from 'lucide-react';
import {
  getDataSource,
  getDemoMode,
  setDataSource,
  setDemoMode,
  subscribeToDemoMode,
  type DemoMode,
  type MarketingDataSource,
} from '../../services/marketing/marketingApi';

const SOURCES: Array<{ value: MarketingDataSource; label: string }> = [
  { value: 'live', label: 'Live API' },
  { value: 'mock', label: 'Mock data' },
];

const MODES: Array<{ value: DemoMode; label: string }> = [
  { value: 'normal', label: 'Normal data' },
  { value: 'slow', label: 'Slow network' },
  { value: 'empty', label: 'Empty workspace' },
  { value: 'error', label: 'Service failing' },
];

/**
 * Chooses where the Hub's data comes from, and — on mock — forces the states
 * that are otherwise unreachable.
 *
 * The source switch exists because the backend is three slices of six: the Hub
 * runs against real segments and campaigns today, but the dashboard figures,
 * sending and test-send have no route behind them. Mock keeps the whole flow
 * reviewable, including on a machine with no API running.
 *
 * The state selector only applies to mock — a live backend's loading and error
 * behaviour is its own. Both leave with the mock layer.
 */
export function DemoStateSelect() {
  const [source, setSource] = useState<MarketingDataSource>(getDataSource);
  const [mode, setMode] = useState<DemoMode>(getDemoMode);

  useEffect(
    () =>
      subscribeToDemoMode(() => {
        setSource(getDataSource());
        setMode(getDemoMode());
      }),
    [],
  );

  return (
    <label className="mkt-demo">
      {source === 'live' ? (
        <Database size={13} strokeWidth={2.3} />
      ) : (
        <FlaskConical size={13} strokeWidth={2.3} />
      )}
      <span className="mkt-demo__label">Data</span>

      <select
        aria-label="Marketing data source"
        onChange={(event) =>
          setDataSource(event.target.value as MarketingDataSource)
        }
        value={source}
      >
        {SOURCES.map((entry) => (
          <option key={entry.value} value={entry.value}>
            {entry.label}
          </option>
        ))}
      </select>

      {source === 'mock' ? (
        <select
          aria-label="Demo data state"
          onChange={(event) => setDemoMode(event.target.value as DemoMode)}
          value={mode}
        >
          {MODES.map((entry) => (
            <option key={entry.value} value={entry.value}>
              {entry.label}
            </option>
          ))}
        </select>
      ) : null}
    </label>
  );
}
