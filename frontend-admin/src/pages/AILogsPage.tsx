import {
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  Filter,
  Sparkles,
  UserRound,
  XCircle,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { DataToolbar } from '../components/DataToolbar';
import { EmptyPanel } from '../components/EmptyPanel';
import { PageIntro } from '../components/PageIntro';
import { Pagination } from '../components/Pagination';
import { ApiError, api, formatDate } from '../services/api';
import { formatResponseTime, pluralize } from '../services/format';
import type { AdminAILog } from '../types/app';

interface AILogsPageProps {
  token: string;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

const PAGE_SIZE = 8;



function responseTimeTone(ms: number | null): 'fast' | 'ok' | 'slow' {
  const value = ms ?? 0;
  if (value < 2000) {
    return 'fast';
  }
  if (value < 8000) {
    return 'ok';
  }
  return 'slow';
}

export function AILogsPage({ token, onToast }: AILogsPageProps) {
  const [logs, setLogs] = useState<AdminAILog[]>([]);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'SUCCESS' | 'FAILURE'>('ALL');
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.getAdminAILogs(token)
      .then(setLogs)
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Unable to load AI logs.';
        onToast('AI logs unavailable', message, 'error');
      });
  }, [onToast, token]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return logs.filter((log) => {
      const matchesQuery =
        !normalized ||
        [log.user_name, log.user_email, log.restaurant_name ?? '', log.query_text, log.reply_text]
          .some((value) => value.toLowerCase().includes(normalized));
      const matchesStatus =
        statusFilter === 'ALL' ||
        (statusFilter === 'SUCCESS' ? log.success : !log.success);
      return matchesQuery && matchesStatus;
    });
  }, [logs, query, statusFilter]);

  const summary = useMemo(() => {
    const total = filtered.length;
    const successes = filtered.filter((log) => log.success).length;
    const timed = filtered
      .map((log) => log.response_time_ms ?? 0)
      .filter((ms) => ms > 0)
      .sort((left, right) => left - right);
    const medianMs =
      timed.length > 0 ? timed[Math.floor((timed.length - 1) / 2)] : 0;
    const suggestions = filtered.reduce((sum, log) => sum + log.suggestions_count, 0);
    return {
      total,
      successRate: total > 0 ? Math.round((successes / total) * 100) : 0,
      medianMs,
      suggestions,
    };
  }, [filtered]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  // Clamp instead of resetting state so shrinking the filter set never
  // strands the view on an empty page.
  const safePage = Math.min(page, totalPages);
  const pageItems = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="RAG monitoring"
        title="AI logs"
        description="Inspect user prompts, retrieval breadth, suggestion output, and response quality across the AI layer."
      />

      <section className="ai-stats" aria-label="Trace summary">
        <article className="ai-stat">
          <span className="ai-stat__label">Traces in view</span>
          <strong>{summary.total}</strong>
          <span className="ai-stat__hint">Matching the current filters</span>
        </article>
        <article className="ai-stat">
          <span className="ai-stat__label">Success rate</span>
          <strong
            className={
              summary.successRate >= 90
                ? 'ai-stat__value--good'
                : summary.successRate >= 60
                  ? ''
                  : 'ai-stat__value--bad'
            }
          >
            {summary.successRate}%
          </strong>
          <span className="ai-stat__hint">Grounded replies without failure</span>
        </article>
        <article className="ai-stat">
          <span className="ai-stat__label">Median response time</span>
          <strong>{formatResponseTime(summary.medianMs, { zeroLabel: 'No data' })}</strong>
          <span className="ai-stat__hint">Across timed traces in view</span>
        </article>
        <article className="ai-stat">
          <span className="ai-stat__label">Suggestions served</span>
          <strong>{summary.suggestions}</strong>
          <span className="ai-stat__hint">Menu items surfaced to users</span>
        </article>
      </section>

      <section className="admin-surface">
        <DataToolbar
          actions={<span className="toolbar-meta">{pluralize(filtered.length, 'trace')}</span>}
          filters={
            <select
              className="page-search page-search--select"
              onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
              value={statusFilter}
            >
              <option value="ALL">All outcomes</option>
              <option value="SUCCESS">Successful</option>
              <option value="FAILURE">Failures</option>
            </select>
          }
          onSearchChange={setQuery}
          searchPlaceholder="Search users, restaurants, prompts..."
          searchValue={query}
        />

        {pageItems.length > 0 ? (
          <>
            <div className="ai-trace-list">
              {pageItems.map((log) => {
                const timeTone = responseTimeTone(log.response_time_ms);
                return (
                  <article className="ai-trace" key={`${log.session_id}-${log.created_at}`}>
                    <header className="ai-trace__header">
                      <span className="ai-trace__avatar">
                        <UserRound size={15} strokeWidth={2.1} />
                      </span>
                      <div className="ai-trace__who">
                        <strong>{log.user_name}</strong>
                        <span title={log.user_email}>
                          {log.restaurant_name ?? 'Platform-wide query'} ·{' '}
                          {formatDate(log.created_at)}
                        </span>
                      </div>
                      <div className="ai-trace__badges">
                        <span
                          className={
                            log.success
                              ? 'ai-trace__outcome ai-trace__outcome--success'
                              : 'ai-trace__outcome ai-trace__outcome--failure'
                          }
                        >
                          {log.success ? (
                            <CheckCircle2 size={12} strokeWidth={2.2} />
                          ) : (
                            <XCircle size={12} strokeWidth={2.2} />
                          )}
                          {log.success ? 'Success' : 'Failure'}
                        </span>
                        <span
                          className={`ai-trace__time ai-trace__time--${timeTone}`}
                          title={`${log.response_time_ms ?? 0} ms`}
                        >
                          <Clock3 size={12} strokeWidth={2.2} />
                          {formatResponseTime(log.response_time_ms, { zeroLabel: 'Cached' })}
                        </span>
                      </div>
                    </header>

                    <div className="ai-trace__convo">
                      <div className="ai-trace__bubble ai-trace__bubble--user">
                        <span className="ai-trace__bubble-label">
                          <UserRound size={12} strokeWidth={2.2} /> User query
                        </span>
                        <p>{log.query_text}</p>
                      </div>
                      <div className="ai-trace__bubble ai-trace__bubble--assistant">
                        <span className="ai-trace__bubble-label">
                          <Bot size={12} strokeWidth={2.2} /> Assistant reply
                        </span>
                        <p>{log.reply_text}</p>
                      </div>
                    </div>

                    <footer className="ai-trace__pipeline">
                      <span className="ai-trace__stage">
                        <Database size={12} strokeWidth={2.2} />
                        Retrieved <strong>{log.retrieved_count}</strong>
                      </span>
                      <span className="ai-trace__arrow">→</span>
                      <span className="ai-trace__stage">
                        <Filter size={12} strokeWidth={2.2} />
                        Filtered <strong>{log.filtered_count}</strong>
                      </span>
                      <span className="ai-trace__arrow">→</span>
                      <span className="ai-trace__stage">
                        <Sparkles size={12} strokeWidth={2.2} />
                        Suggestions <strong>{log.suggestions_count}</strong>
                      </span>
                    </footer>
                  </article>
                );
              })}
            </div>
            <Pagination onPageChange={setPage} page={safePage} totalPages={totalPages} />
          </>
        ) : (
          <EmptyPanel description="AI chat sessions will appear here once customers start interacting with the assistant." title="No AI traces yet" />
        )}
      </section>
    </div>
  );
}
