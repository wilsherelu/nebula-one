import { Alert, Button, InputNumber, Select } from '@arco-design/web-react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { buildSolvePayload, solveIdempotencyKey } from '../../calculation/solveContract';
import type { CalculationMethodVersion } from '../../api/types';
import { useI18n } from '../../i18n';
import { ErrorState } from '../../components/ui/States';

export function MethodRun({ applicationId, revisionId, graph, purpose, version, dirty }: {
  applicationId: string; revisionId: string; graph?: Record<string, unknown>; purpose: string; version: CalculationMethodVersion; dirty: boolean;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const application = useQuery({ queryKey: ['method-run-application', applicationId], queryFn: () => api.application(applicationId) });
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const products = nodes.flatMap(node => (Array.isArray(node.outputs) ? node.outputs : []).filter((port: Record<string, unknown>) => port.isProduct
    && port.id && port.flowUuid && port.unit && port.unitGroupUuid && port.unitGroupVersion)
    .map((port: Record<string, unknown>) => ({ ...port, selectionId: `${node.id}::${port.id}`, processName: node.name || node.id })));
  const [productId, setProductId] = useState('');
  const [amount, setAmount] = useState<number>(1);
  const product = products.find(port => port.selectionId === productId);
  const solve = useMutation({ mutationFn: async () => {
    const task = purpose === 'organization' ? 'organization' as const : 'pcf' as const;
    const ref = { method_id: version.method_id, version: version.version, content_sha256: version.content_sha256! };
    const demand = [{ reference_flow_uuid: product.flowUuid, amount, unit: product.unit,
      unit_group_uuid: product.unitGroupUuid, unit_group_version: product.unitGroupVersion }];
    return api.solveAndFreeze(applicationId, revisionId, buildSolvePayload({ demand, task, calculationMethodRef: ref,
      idempotencyKey: await solveIdempotencyKey(task, revisionId, JSON.stringify(demand), ref) }));
  }, onSuccess: result => navigate(`/applications/${applicationId}/results?snapshot=${result.id}&view=${purpose === 'organization' ? 'organization' : 'pcf'}`) });
  if (application.data?.context.template_locked || purpose === 'cbam' || purpose === 'organization') return <Link to={`/applications/${applicationId}/workbench?revision=${revisionId}`}>{t('cm.calculateInProject')}</Link>;
  if (purpose === 'custom') return <Alert type="info" content={t('cm.customPurposeNote')} />;
  return <div className="form-actions">
    <Select aria-label={t('cm.runProduct')} style={{ width: 260 }} value={productId || undefined}
      options={products.map(port => ({ value: port.selectionId, label: `${port.processName} · ${port.name || port.id} · ${port.unit}` }))} onChange={setProductId} />
    <InputNumber aria-label={t('cm.runAmount')} value={amount} min={Number.EPSILON} onChange={setAmount} suffix={product?.unit} />
    <Button type="primary" loading={solve.isPending} disabled={!application.data || dirty || version.status !== 'ready' || !product || !Number.isFinite(amount) || amount <= 0}
      onClick={() => solve.mutate()}>{t('cm.runMethod')}</Button>
    {application.error || solve.error ? <ErrorState error={application.error || solve.error} /> : null}
  </div>;
}
