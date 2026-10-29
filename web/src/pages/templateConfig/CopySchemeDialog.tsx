import { useRef, useState } from 'react';
import { Alert, Button, Input, Modal, Select } from '@arco-design/web-react';
import { useMutation } from '@tanstack/react-query';
import { templateMethodsApi, type TemplateAccountingMethod, type TemplateMethodCopyResult } from '../../api/templateMethods';
import { useI18n } from '../../i18n';

/**
 * 复制并调整: the only choices here are the reader's own - the copy's name and, for CBAM, which
 * frozen boundary the variant narrows. Everything else comes from the exact template version, so a
 * copy can never be pointed at a different model or invent rules the package does not declare.
 */
export function CopySchemeDialog({ templateId, scheme, defaultName, onClose, onCopied }: {
  templateId: string;
  scheme: TemplateAccountingMethod;
  defaultName: string;
  onClose: () => void;
  onCopied: (result: TemplateMethodCopyResult) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(defaultName);
  const boundaries = (scheme.cbam_boundaries ?? []).filter(item => item.boundary_type === 'cbam_trial');
  const [boundaryRef, setBoundaryRef] = useState(boundaries.length === 1 ? boundaries[0].id : '');
  // A double click lands before the pending state re-renders, so the second request is refused here
  // rather than answered by the server's name conflict.
  const inFlight = useRef(false);
  const copy = useMutation({
    mutationFn: () => templateMethodsApi.copyOfficial(templateId, {
      method_key: scheme.method_key,
      name: name.trim(),
      cbam_boundary_ref: boundaryRef || null,
    }),
    onSettled: () => { inFlight.current = false; },
    onSuccess: onCopied,
  });
  const needsBoundary = scheme.method_group === 'cbam';
  const selected = boundaries.find(item => item.id === boundaryRef) ?? null;
  const blocked = !name.trim() || (needsBoundary && !boundaryRef) || copy.isPending;
  return <Modal visible title={t('tm.copyTitle')} className="template-copy-dialog"
    style={{ width: 560, maxWidth: 'calc(100vw - 32px)' }} footer={null} onCancel={onClose}
    maskClosable={!copy.isPending} closable={!copy.isPending} escToExit={!copy.isPending} autoFocus>
    <p className="helper-text">
      {t('tm.copyHint', { rules: scheme.rule_source.declared_count, ports: scheme.rule_source.port_count })}
    </p>
    <div className="template-copy-dialog__field">
      <label htmlFor="template-copy-name">{t('tm.copyName')}</label>
      <Input id="template-copy-name" value={name} disabled={copy.isPending} onChange={setName} />
    </div>
    {needsBoundary ? <div className="template-copy-dialog__field">
      <label htmlFor="template-copy-boundary">{t('tm.copyBoundary')}</label>
      <Select id="template-copy-boundary" aria-label={t('tm.copyBoundary')} value={boundaryRef}
        disabled={copy.isPending || !boundaries.length}
        onChange={value => setBoundaryRef(String(value ?? ''))}
        options={boundaries.map(item => ({ value: item.id, label: t('tm.frozenBoundaryOption', {
          processes: item.included_process_count, rules: item.included_flow_rule_count }) }))} />
      {boundaries.length ? null : <p className="helper-text">{t('tm.copyBoundaryMissing')}</p>}
      {selected ? <details className="template-copy-dialog__source">
        <summary>{t('tm.sourceDetail')}</summary>
        <dl>
          <dt>{t('tm.boundaryRecordName')}</dt>
          <dd>{selected.name}</dd>
          <dt>{t('tm.boundaryId')}</dt>
          <dd><code>{selected.id}</code></dd>
          <dt>{t('tm.boundaryPackage')}</dt>
          <dd>{selected.method_package_ref ?? '—'}</dd>
          <dt>{t('tm.contentHash')}</dt>
          <dd><code>{selected.graph_sha256 ?? '—'}</code></dd>
        </dl>
      </details> : null}
    </div> : null}
    {copy.isError ? <Alert type="error" showIcon
      content={copy.error instanceof Error ? copy.error.message : String(copy.error)} /> : null}
    <div className="form-actions">
      <Button disabled={copy.isPending} onClick={onClose}>{t('workspace.draftCancel')}</Button>
      <Button type="primary" loading={copy.isPending} disabled={blocked}
        onClick={() => { if (inFlight.current || blocked) return; inFlight.current = true; copy.mutate(); }}>
        {t('tm.copySubmit')}
      </Button>
    </div>
  </Modal>;
}
