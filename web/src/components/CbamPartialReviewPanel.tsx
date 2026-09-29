import { Alert, Button, Select } from '@arco-design/web-react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../api/client';
import type { BoundaryDefinition, CbamPartialReviewRequest, MethodPackage, SolvedSystemSnapshot } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorState } from './ui/States';

export function CbamPartialReviewPanel({ applicationId, snapshot, snapshots, method, boundaries, methodPackages = [] }: {
  applicationId: string; snapshot: SolvedSystemSnapshot; snapshots: SolvedSystemSnapshot[];
  method: MethodPackage; boundaries: BoundaryDefinition[]; methodPackages?: MethodPackage[];
}) {
  const { t, formatNumber } = useI18n();
  const number = (value: number) => formatNumber(value, { maximumSignificantDigits: undefined, maximumFractionDigits: 6 });
  const [downloadError, setDownloadError] = useState<Error | null>(null);
  const [periodId, setPeriodId] = useState('');
  const [sourceSnapshotId, setSourceSnapshotId] = useState('');
  const [boundaryId, setBoundaryId] = useState('');
  const [factorRef, setFactorRef] = useState('');
  const [showInputs, setShowInputs] = useState(false);
  const [conditions, setConditions] = useState<Record<string, { status: string; evidence_sha256: string }>>({});
  const formula = method.manifest.formula_graph as { source_direct_method?: { reference?: string }; indirect_activity?: { process_uuid?: string; flow_uuid?: string }; required_condition_keys?: string[];
    condition_labels?: Record<string, string>; condition_rules?: Record<string, { allowed_statuses?: Array<{ code: string; label: string }> }> };
  const sourceMethod = formula.source_direct_method?.reference;
  const basis = snapshot.provider_receipt.calculation_basis as { demand?: unknown; model_derivation?: { source_graph_sha256?: string } } | undefined;
  const candidates = snapshots.filter(item => {
    const candidateBasis = item.provider_receipt.calculation_basis as { purpose?: string; demand?: unknown; model_derivation?: { source_graph_sha256?: string } } | undefined;
    return item.system_revision_id === snapshot.system_revision_id && candidateBasis?.purpose === 'cbam'
      && JSON.stringify(candidateBasis.demand) === JSON.stringify(basis?.demand)
      && (!basis?.model_derivation?.source_graph_sha256
        || candidateBasis.model_derivation?.source_graph_sha256 === basis.model_derivation.source_graph_sha256);
  });
  const sourceSnapshot = candidates.find(item => item.id === snapshot.id)
    ?? candidates.find(item => item.id === sourceSnapshotId)
    ?? (candidates.length === 1 ? candidates[0] : undefined);
  const sourceBasis = sourceSnapshot?.provider_receipt.calculation_basis as { model_derivation?: { source_graph_sha256?: string } } | undefined;
  const boundaryCandidates = boundaries.filter(item => item.status === 'frozen' && item.method_package_ref === sourceMethod
    && item.geographic_scope.graph_sha256 === sourceBasis?.model_derivation?.source_graph_sha256
    && (item.geographic_scope.source_system_revision_id === snapshot.system_revision_id
      || (!item.geographic_scope.source_system_revision_id && item.name.endsWith(` / ${snapshot.system_revision_id}`))));
  const boundary = boundaryCandidates.find(item => item.id === boundaryId)
    ?? (boundaryCandidates.length === 1 ? boundaryCandidates[0] : undefined);
  const periods = useQuery({ queryKey: ['periods', applicationId], queryFn: () => api.periods(applicationId) });
  const period = boundary?.period_id ? periods.data?.find(item => item.id === boundary.period_id)
    : (periods.data?.length === 1 ? periods.data[0] : periods.data?.find(item => item.id === periodId));
  const factorPackages = methodPackages.filter(item => {
    const factor = item.manifest.factor as { eligible_partial_method_ref?: string; process_uuid?: string; flow_uuid?: string; boundary?: string } | undefined;
    const classification = method.manifest.classification_rules as { factor_boundary?: string } | undefined;
    return item.package_kind === 'cbam_electricity_factor' && item.jurisdiction === 'EU'
      && factor?.eligible_partial_method_ref === `${method.package_id}@${method.version}`
      && factor.process_uuid === formula.indirect_activity?.process_uuid
      && factor.flow_uuid === formula.indirect_activity?.flow_uuid
      && factor.boundary === classification?.factor_boundary
      && (!period || Boolean(item.valid_from && item.valid_to && item.valid_from <= period.start_date && item.valid_to >= period.end_date));
  });
  const request: CbamPartialReviewRequest | undefined = boundary && period ? {
    method_package_ref: `${method.package_id}@${method.version}`,
    reporting_period_id: period.id, boundary_definition_id: boundary.id,
    ...(factorRef ? { eligible_electricity_factor_ref: factorRef } : {}),
    ...(Object.keys(conditions).length ? { condition_declarations: conditions } : {}),
  } : undefined;
  const review = useQuery({ queryKey: ['cbam-partial-review', sourceSnapshot?.id, request],
    queryFn: () => api.cbamPartialReview(sourceSnapshot!.id, request!),
    enabled: Boolean(sourceSnapshot && request) });
  const missing = review.data?.coverage.missing ?? [];
  const missingItems = [
    ...(missing.includes('eligible_sinter_electricity_factor') ? [t('cbam.eligibleFactor')] : []),
    ...((formula.required_condition_keys ?? []).some(key => missing.includes(key)) ? [t('cbam.attributionEvidence')] : []),
  ];
  if (missing.some(key => key !== 'eligible_sinter_electricity_factor' && !(formula.required_condition_keys ?? []).includes(key))) {
    missingItems.push(t('cbam.otherEvidence'));
  }
  const updateCondition = (key: string, status: string) => setConditions(previous => {
    if (!status) return Object.fromEntries(Object.entries(previous).filter(([name]) => name !== key));
    return { ...previous, [key]: { status, evidence_sha256: previous[key]?.evidence_sha256 ?? '' } };
  });
  const download = async () => {
    if (!sourceSnapshot || !request) return;
    setDownloadError(null);
    try {
      const blob = await api.cbamPartialReviewReport(sourceSnapshot.id, request);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `cbam-partial-review-${sourceSnapshot.id}.md`;
      link.click(); URL.revokeObjectURL(url);
    } catch (error) { setDownloadError(error instanceof Error ? error : new Error(String(error))); }
  };
  return <section className="cbam-review">
    <div className="cbam-review__heading"><div><h2>{t('task.cbam')}</h2><span>{t('cbam.trialNote')}</span></div>
      {review.data ? <Button size="small" onClick={download}>{t('cbam.downloadReview')}</Button> : null}</div>
    {review.data ? <>
      <div className="cbam-review__metrics">
        <div><span>{t('cbam.directIncluded')}</span><strong>{number(Number(review.data.components.direct.value))}</strong><small>{review.data.components.direct.unit}</small></div>
        <div><span>{t('cbam.indirect')}</span><strong>{review.data.components.sinter_precursor_indirect.value == null ? t('cbam.pending') : number(Number(review.data.components.sinter_precursor_indirect.value))}</strong><small>{review.data.components.sinter_precursor_indirect.unit}</small></div>
        <div><span>{t('cbam.selectedTotal')}</span><strong>{review.data.specific_embedded_emissions.value == null ? t('cbam.notCalculated') : number(Number(review.data.specific_embedded_emissions.value))}</strong><small>{review.data.specific_embedded_emissions.unit}</small></div>
      </div>
      <div className="cbam-review__next"><span>{missingItems.length ? t('cbam.missing', { items: missingItems.join('、') }) : t('cbam.evidenceReady')}</span>
        {missingItems.length ? <Button type="primary" size="small" onClick={() => setShowInputs(true)}>{t('cbam.supply')}</Button> : null}</div>
      {review.data.components.user_supply_electricity_trial ? <Alert type="info" title={t('cbam.localSupply')}
        content={t('cbam.localSupplyNote', { value: number(Number(review.data.components.user_supply_electricity_trial.value)), unit: review.data.components.user_supply_electricity_trial.unit, project: review.data.components.user_supply_electricity_trial.source_project_id, version: review.data.components.user_supply_electricity_trial.source_version })} /> : null}
      <details className="result-details"><summary>{t('cbam.components')}</summary><p>{t('cbam.sinterElectricity')}：{number(Number(review.data.components.sinter_precursor_indirect.electricity_activity.value))} {review.data.components.sinter_precursor_indirect.electricity_activity.unit}</p></details>
    </> : null}
    {review.isLoading ? <p role="status">{t('cbam.loading')}</p> : null}
    {!sourceSnapshot || !boundary ? <p>{t('cbam.noBoundary')}</p> : null}
    {periods.isError ? <ErrorState error={periods.error} /> : null}
    {review.isError ? <ErrorState error={review.error} onRetry={() => review.refetch()} /> : null}
    {!review.data && !showInputs ? <Button onClick={() => setShowInputs(true)}>{t('cbam.supply')}</Button> : null}
    {showInputs ? <div className="cbam-review__inputs"><div className="cbam-review__inputs-heading"><h3>{t('cbam.supply')}</h3><Button size="small" onClick={() => setShowInputs(false)}>{t('cbam.collapse')}</Button></div>
      {candidates.length > 1 && snapshot.id !== sourceSnapshot?.id ? <label>{t('cbam.record')}<Select aria-label={t('cbam.chooseRecord')} value={sourceSnapshotId} onChange={setSourceSnapshotId}
        placeholder={t('cbam.chooseMatchingRecord')} options={candidates.map(item => ({ label: item.created_at, value: item.id }))} /></label> : null}
      {boundaryCandidates.length > 1 ? <label>{t('cbam.frozenBoundary')}<Select aria-label={t('cbam.chooseBoundary')} value={boundaryId} onChange={setBoundaryId}
        placeholder={t('cbam.chooseMatchingBoundary')} options={boundaryCandidates.map(item => ({ label: item.name, value: item.id }))} /></label> : null}
      {boundary && !boundary.period_id && (periods.data?.length ?? 0) > 1 ? <label>{t('cbam.period')}<Select aria-label={t('cbam.reviewPeriod')} value={periodId} onChange={setPeriodId} options={(periods.data ?? []).map(item => ({ label: item.name, value: item.id }))} /></label> : null}
      {formula.required_condition_keys?.length ? <>
        {factorPackages.length ? <label>{t('cbam.eligibleFactor')}<Select aria-label={t('cbam.chooseFactor')} value={factorRef} onChange={setFactorRef}
          options={[{ label: t('cbam.noFactorChoice'), value: '' }, ...factorPackages.map(item => ({ label: `${item.package_id} · ${item.version}`, value: `${item.package_id}@${item.version}` }))]} /></label>
          : <p>{t('cbam.noFactor')}</p>}
        <p>{t('cbam.conditionNote')}</p>
        {(formula.required_condition_keys ?? []).map(key => <div key={key} className="project-period-form">
          <label>{formula.condition_labels?.[key] ?? key}<Select aria-label={t('cbam.conditionStatus', { key })} value={conditions[key]?.status ?? ''}
            onChange={value => updateCondition(key, value)} options={[{ label: t('cbam.undeclared'), value: '' },
              ...(formula.condition_rules?.[key]?.allowed_statuses ?? []).map(item => ({ label: item.label, value: item.code }))]} /></label>
          {conditions[key] ? <label>{t('cbam.evidenceHash', { key })}<input aria-label={t('cbam.evidenceHash', { key })} value={conditions[key].evidence_sha256}
            onChange={event => setConditions(previous => ({ ...previous, [key]: { ...previous[key], evidence_sha256: event.target.value } }))} /></label> : null}
        </div>)}
      </> : null}
    </div> : null}
    {review.data ? <details className="result-details"><summary>{t('cbam.basis')}</summary>
      <ul>{(review.data.components.direct.exchanges ?? []).map(item => <li key={item.exchange_id}>{item.exchange_id} · {item.amount ?? '—'} {item.unit} · {item.clause ?? t('cbam.clausePending')}</li>)}</ul>
      <small>{t('cbam.methodEvidence', { method: review.data.method_package.reference, snapshot: review.data.source_snapshot.id, hash: review.data.content_sha256 })}</small>
    </details> : null}
    {downloadError ? <ErrorState error={downloadError} /> : null}
  </section>;
}
