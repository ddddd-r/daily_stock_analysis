import type React from 'react';
import type {
  ReportMonitoring as ReportMonitoringType,
  MonitoringIndicator,
  MonitoringStatus,
} from '../../types/analysis';
import { Card } from '../common';

interface ReportMonitoringProps {
  monitoring?: ReportMonitoringType;
}

const STATUS_META: Record<MonitoringStatus, { emoji: string; label: string; color: string }> = {
  alert: { emoji: '🔴', label: '告警', color: '#ff4466' },
  ok: { emoji: '🟢', label: '正常', color: '#00ff88' },
  unavailable: { emoji: '⚪', label: '数据不可用', color: 'var(--text-muted-text)' },
  ignored: { emoji: '⚫', label: '本档忽略', color: 'var(--text-muted-text)' },
};

const IndicatorRow: React.FC<{ ind: MonitoringIndicator }> = ({ ind }) => {
  const meta = STATUS_META[ind.status] ?? STATUS_META.unavailable;
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-white/5 last:border-0">
      <span className="shrink-0 text-sm leading-5" title={meta.label}>
        {meta.emoji}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm text-white truncate">{ind.display}</span>
          <span className="text-sm font-mono shrink-0" style={{ color: meta.color }}>
            {ind.valueStr}
          </span>
        </div>
        <div className="text-xs text-muted-text mt-0.5">
          {ind.rule}
          {ind.note ? <span className="opacity-70">（{ind.note}）</span> : null}
        </div>
      </div>
    </div>
  );
};

/**
 * 投资组合监控仪表盘（港股/美股）
 * 依据「低/中/高风险规则集」对技术 / 基本面 / 股息三大类指标评估并输出告警。
 */
export const ReportMonitoring: React.FC<ReportMonitoringProps> = ({ monitoring }) => {
  if (!monitoring || !monitoring.categories?.length) {
    return null;
  }

  const { tierLabel, nBars, summary, categories, alerts, deferred } = monitoring;

  return (
    <Card variant="bordered" padding="md">
      <div className="mb-3 flex items-baseline gap-2 flex-wrap">
        <span className="label-uppercase">PORTFOLIO MONITOR</span>
        <h3 className="text-base font-semibold text-white">投资组合监控仪表盘</h3>
      </div>

      {/* 摘要条 */}
      <div className="flex items-center gap-3 flex-wrap text-xs mb-3">
        <span className="px-2 py-0.5 rounded bg-elevated border border-white/10 text-white">
          风险档位：{tierLabel}
        </span>
        <span style={{ color: '#ff4466' }}>🔴 告警 {summary?.alerts ?? 0}</span>
        <span className="text-muted-text">⚪ 数据不可用 {summary?.unavailable ?? 0}</span>
        <span className="text-muted-text">基于 {nBars} 根日K线</span>
      </div>

      {/* 触发告警优先展示 */}
      {alerts?.length ? (
        <div className="mb-3 rounded-lg border border-danger/30 bg-danger/5 p-3">
          <div className="text-xs font-semibold mb-1.5" style={{ color: '#ff4466' }}>
            🔴 触发告警 {alerts.length}
          </div>
          <ul className="space-y-1">
            {alerts.map((a) => (
              <li key={a.key} className="text-xs text-white">
                <span className="font-medium">{a.display}</span>
                <span className="font-mono mx-1" style={{ color: '#ff4466' }}>
                  {a.valueStr}
                </span>
                <span className="text-muted-text">—— {a.rule}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* 各类别明细 */}
      <div className="space-y-3">
        {categories.map((cat) => (
          <div key={cat.key}>
            <div className="text-xs font-semibold text-muted-text uppercase tracking-wide mb-1">
              {cat.label}
            </div>
            <div className="rounded-lg bg-elevated border border-white/5 px-3">
              {cat.indicators.map((ind) => (
                <IndicatorRow key={ind.key} ind={ind} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* 暂未实现的类别 */}
      {deferred?.length ? (
        <div className="mt-3 space-y-1">
          {deferred.map((d) => (
            <p key={d.key} className="text-xs text-muted-text">
              ⏸️ <span className="font-medium">{d.label}</span>：{d.reason}
            </p>
          ))}
        </div>
      ) : null}
    </Card>
  );
};
