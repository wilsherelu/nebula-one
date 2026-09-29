import { Alert, Button } from '@arco-design/web-react';
import { IconDownload, IconFile } from '@arco-design/web-react/icon';
import { useState } from 'react';
import { api } from '../api/client';
import type { NativeClimateDomain, NativeClimateEnvelope } from '../api/types';
import { MetricCard } from './ui/MetricCard';
import { ErrorState } from './ui/States';

/**
 * The engine reports coverage only for the states a solve actually met, so a missing key means
 * that state did not occur rather than that it was zero.
 */
const COVERAGE_LABELS: Record<string, string> = {
  explicit_nonzero: '有非零排放因子',
  explicit_zero: '因子明确为零',
  no_cf: '未纳入特征化',
};

const DOMAIN_LABELS: Record<string, string> = {
  foreground: '前台生产过程',
  native_background: '已关联的背景供应',
};

/** Values the contract publishes as machine tokens would read as jargon in a status row. */
const STATEMENT_LABELS: Record<string, string> = {
  not_assessed: '未评估',
  not_asserted_by_local_vector_metadata: '本地向量元数据未作声明',
  partial_background_leaf_only_not_complete_product_carbon_footprint:
    '背景覆盖止于已关联的背景供应叶子，本结果不构成完整产品碳足迹',
};

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 8 }).format(value);
}

function coverageText(domain: NativeClimateDomain): string {
  return Object.entries(domain.coverage)
    .map(([state, count]) => `${COVERAGE_LABELS[state] ?? state} ${new Intl.NumberFormat('zh-CN').format(count)} 项`)
    .join(' · ');
}

function readText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : JSON.stringify(value);
}

export function NativeClimatePanel({ envelope, snapshotId }: { envelope: NativeClimateEnvelope; snapshotId: string }) {
  const answer = envelope.response;
  const domains = Object.entries(answer.domains);
  const merged = answer.merge_status === 'merged';
  const total = answer.unified_climate_total;
  const negatives = domains.reduce((sum, [, domain]) => sum + domain.negative_cf_exchange_count, 0);
  const pin = envelope.request;
  const [artifactAction, setArtifactAction] = useState<'excel' | 'report' | null>(null);
  const [artifactError, setArtifactError] = useState<Error | null>(null);
  const [failedAction, setFailedAction] = useState<'excel' | 'report' | null>(null);

  const runArtifactAction = async (action: 'excel' | 'report') => {
    if (artifactAction) return;
    setArtifactError(null);
    setFailedAction(null);
    let reportWindow: Window | null = null;
    if (action === 'report') {
      reportWindow = window.open('about:blank', '_blank');
      if (!reportWindow) {
        setArtifactError(new Error('浏览器已拦截报告窗口，请允许弹出窗口后重试。'));
        setFailedAction(action);
        return;
      }
      reportWindow.opener = null;
    }
    setArtifactAction(action);
    try {
      const blob = action === 'excel' ? await api.nativeClimateExport(snapshotId) : await api.nativeClimateReport(snapshotId);
      if (typeof URL.createObjectURL !== 'function') throw new Error('当前浏览器无法打开生成的文件。');
      const url = URL.createObjectURL(blob);
      if (action === 'excel') {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `native-background-climate-${snapshotId}.xlsx`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
      } else if (reportWindow) {
        reportWindow.location.href = url;
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (requestError) {
      reportWindow?.close();
      setArtifactError(requestError instanceof Error ? requestError : new Error('部分背景气候结果文件生成失败，请重试。'));
      setFailedAction(action);
    } finally {
      setArtifactAction(null);
    }
  };

  return <div className="native-climate-result">
    <div className="native-climate-result__head">
      <h3>部分背景下的气候变化结果</h3>
      <p className="helper-text">{STATEMENT_LABELS[answer.claim_limit] ?? answer.claim_limit}</p>
    </div>

    <div className="native-climate-result__actions" aria-label="部分背景气候结果导出">
      <Button icon={<IconDownload />} loading={artifactAction === 'excel'} disabled={Boolean(artifactAction)} onClick={() => runArtifactAction('excel')}>Excel 明细</Button>
      <Button icon={<IconFile />} loading={artifactAction === 'report'} disabled={Boolean(artifactAction)} onClick={() => runArtifactAction('report')}>HTML 报告</Button>
    </div>
    {artifactError ? <ErrorState error={artifactError} onRetry={failedAction ? () => runArtifactAction(failedAction) : undefined} /> : null}

    {merged && total !== null
      ? <div className="native-climate-result__summary">
        <MetricCard label="气候变化合计（含已关联背景）" value={formatNumber(total)} unit={answer.indicator.unit} />
        <dl className="native-climate-result__facts">
          <div><dt>指标</dt><dd>{answer.indicator.name} · {answer.indicator.category}</dd></div>
          <div><dt>核算方法</dt><dd>{answer.indicator.method}</dd></div>
          <div><dt>方法包版本</dt><dd>{answer.method_package_id} · {answer.method_package_version}</dd></div>
        </dl>
      </div>
      : null}

    {merged && total === null
      ? <Alert type="error" title="合并状态缺少合计" content="来源结果声明已合并却没有给出合计，One 不会自行相加补出该数值。请重新计算并向来源核实。" />
      : null}

    {!merged
      ? <Alert
        type="warning"
        title="本次结果按来源分域给出，未合并"
        content={<>各域口径不一致，因此没有合计值；把下列数字相加会得到一个来源未认可的结论。
          {answer.merge_blockers.length ? <ul className="native-climate-result__blockers">{answer.merge_blockers.map((blocker, index) => <li key={index}>{Object.entries(blocker).map(([key, value]) => `${key}: ${readText(value)}`).join(' · ')}</li>)}</ul> : null}
        </>}
      />
      : null}

    <section className="native-climate-result__domains" aria-label="来源分域结果">
      {domains.map(([key, domain]) => <div className="native-climate-domain-row" key={key}>
        <strong>{DOMAIN_LABELS[key] ?? key}</strong>
        <span className="tabular">{formatNumber(domain.contribution_value)} {domain.indicator_unit}</span>
        <small>{coverageText(domain)} · 来源 {domain.source_namespace}</small>
      </div>)}
    </section>

    {negatives ? <p className="helper-text">其中含 {negatives} 项负贡献，代表抵消性的投入输出，不等于永久碳移除（碳储存永久性：{STATEMENT_LABELS[answer.carbon_storage_permanence] ?? answer.carbon_storage_permanence}）。</p> : null}
    <p className="helper-text">本页只报告总量、覆盖范围与版本引用，不展示逐条背景交换明细。</p>

    <details className="native-climate-result__evidence"><summary>版本与来源证据</summary>
      <dl>
        <div><dt>方法包</dt><dd>{pin.method_package_id}@{pin.method_package_version}</dd></div>
        <div><dt>方法包内容哈希</dt><dd className="tabular">{pin.method_package_sha256}</dd></div>
        <div><dt>运行时清单哈希</dt><dd className="tabular">{pin.runtime_manifest_sha256}</dd></div>
        <div><dt>背景数据版本</dt><dd>{pin.database_release}</dd></div>
        <div><dt>流快照哈希</dt><dd className="tabular">{pin.flow_snapshot_hash}</dd></div>
        <div><dt>依赖快照哈希</dt><dd className="tabular">{pin.reference_dependency_snapshot_hash}</dd></div>
        <div><dt>背景系统模型</dt><dd>{STATEMENT_LABELS[answer.provider_system_model_evidence] ?? answer.provider_system_model_evidence}</dd></div>
        <div><dt>来源合同</dt><dd>{envelope.source_contract.repository} {envelope.source_contract.commit.slice(0, 12)} · {envelope.source_contract.document}</dd></div>
        <div><dt>来源合同文本哈希</dt><dd className="tabular">{envelope.source_contract.document_sha256}</dd></div>
      </dl>
    </details>
  </div>;
}
