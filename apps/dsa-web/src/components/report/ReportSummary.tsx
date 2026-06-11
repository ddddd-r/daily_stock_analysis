import React from 'react';
import type { AnalysisResult, AnalysisReport } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { ReportStrategy } from './ReportStrategy';
import { ReportMonitoring } from './ReportMonitoring';
import { ReportNews } from './ReportNews';
import { ReportDetails } from './ReportDetails';

interface ReportSummaryProps {
  data: AnalysisResult | AnalysisReport;
  isHistory?: boolean;
}

/**
 * 完整报告展示组件
 * 整合概览、策略、资讯、详情四个区域
 */
export const ReportSummary: React.FC<ReportSummaryProps> = ({
  data,
  isHistory = false,
}) => {
  // 兼容 AnalysisResult 和 AnalysisReport 两种数据格式
  const report: AnalysisReport = 'report' in data ? data.report : data;
  // 使用 report id，因为 queryId 在批量分析时可能重复，且历史报告详情接口需要 recordId 来获取关联资讯和详情数据
  const recordId = report.meta.id;

  const { meta, summary, strategy, details, monitoring } = report;
  const modelUsed = (meta.modelUsed || '').trim();
  const shouldShowModel = Boolean(
    modelUsed && !['unknown', 'error', 'none', 'null', 'n/a'].includes(modelUsed.toLowerCase()),
  );

  return (
    <div className="space-y-3 animate-fade-in">
      {/* 概览区（首屏） */}
      <ReportOverview
        meta={meta}
        summary={summary}
        isHistory={isHistory}
      />

      {/* 策略点位区 */}
      <ReportStrategy strategy={strategy} />

      {/* 投资组合监控区（港股/美股） */}
      <ReportMonitoring monitoring={monitoring} />

      {/* 资讯区 */}
      <ReportNews recordId={recordId} />

      {/* 透明度与追溯区 */}
      <ReportDetails details={details} recordId={recordId} />

      {/* 分析模型标记（Issue #528）— 报告末尾 */}
      {shouldShowModel && (
        <p className="text-xs text-gray-500 mt-3">
          分析模型: {modelUsed}
        </p>
      )}

      {/* 免责声明 */}
      <p className="text-xs text-gray-500 mt-2 leading-relaxed border-t border-white/5 pt-2">
        免责声明：本报告由 AI 自动生成，所有内容（含评分、监控告警与买卖点位）仅供研究参考，
        不构成任何投资建议、要约或保证。市场有风险，投资需谨慎，据此操作风险自担。
      </p>
    </div>
  );
};
