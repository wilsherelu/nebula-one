import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Input, Modal } from '@arco-design/web-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { templateMethodsApi, type TemplateSaveResult } from '../../api/templateMethods';
import { useI18n } from '../../i18n';
import { ErrorState, LoadingState } from '../../components/ui/States';

const REASONS = ['METHOD_NOT_VALIDATED', 'METHOD_ALREADY_IN_TEMPLATE', 'METHOD_HAS_NO_VERSION',
  'METHOD_BOUNDARY_NOT_FROZEN_IN_SOURCE'];

/**
 * 保存为我的模板: a short confirmation inside the workspace, not a second finalize form.
 *
 * The server plan names the exact data version, package pins and the reader's own checked schemes,
 * so the only free text here is the new template's name and version. A scheme that cannot be frozen
 * is listed with the reason instead of being offered, and a bound package that no longer resolves
 * blocks the save rather than quietly publishing a narrower template.
 */
export function SaveTemplateDialog({ templateId, onClose, onSaved }: {
  templateId: string;
  onClose: () => void;
  onSaved: (result: TemplateSaveResult) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const plan = useQuery({ queryKey: ['template-save-plan', templateId],
    queryFn: () => templateMethodsApi.savePlan(templateId) });
  const [title, setTitle] = useState('');
  const [version, setVersion] = useState('');
  const [unchecked, setUnchecked] = useState<string[]>([]);
  // A disabled button alone does not stop a double click: the pending state has not re-rendered yet
  // when the second click lands, and two saves would publish the same template version twice.
  const inFlight = useRef(false);
  useEffect(() => {
    if (plan.data) { setTitle(previous => previous || plan.data.suggested_title);
      setVersion(previous => previous || plan.data.suggested_version); }
  }, [plan.data]);
  const candidates = plan.data?.user_methods ?? [];
  const chosen = candidates.filter(item => item.savable && !unchecked.includes(item.method_id));
  const save = useMutation({
    mutationFn: () => templateMethodsApi.saveTemplate(templateId, {
      title: title.trim(), version: version.trim(),
      user_methods: chosen.map(item => ({ method_id: item.method_id, version: item.version,
        content_sha256: item.content_sha256 ?? '' })),
    }),
    onSettled: () => { inFlight.current = false; },
    onSuccess: result => {
      void queryClient.invalidateQueries({ queryKey: ['seed-project-templates'] });
      onSaved(result);
    },
  });
  const unresolved = plan.data?.unresolved_method_package_refs ?? [];
  const blocked = !plan.data || !title.trim() || !version.trim() || !!unresolved.length || save.isPending;
  return <Modal visible title={t('tm.saveTitle')} className="template-save-dialog"
    style={{ width: 620, maxWidth: 'calc(100vw - 32px)' }} footer={null} onCancel={onClose}
    maskClosable={!save.isPending} closable={!save.isPending} escToExit={!save.isPending} autoFocus>
    {plan.isLoading ? <LoadingState rows={3} /> : null}
    {plan.isError ? <ErrorState error={plan.error} onRetry={() => plan.refetch()} /> : null}
    {plan.data ? <>
      <p className="helper-text">{t('tm.saveHint')}</p>
      <p className="template-save-dialog__fact">{t('tm.savePins', { count: plan.data.method_pins.length })}</p>
      {unresolved.length ? <Alert type="warning" showIcon content={
        t('tm.saveUnresolved', { count: unresolved.length, refs: unresolved.join('、') })} /> : null}
      <div className="template-save-dialog__field">
        <label htmlFor="template-save-name">{t('tm.saveName')}</label>
        <Input id="template-save-name" value={title} maxLength={255} disabled={save.isPending} onChange={setTitle} />
      </div>
      <div className="template-save-dialog__field">
        <label htmlFor="template-save-version">{t('tm.saveVersion')}</label>
        <Input id="template-save-version" value={version} maxLength={32} disabled={save.isPending} onChange={setVersion} />
      </div>
      <section className="template-save-dialog__schemes">
        <h4>{t('tm.saveSchemes')}</h4>
        {chosen.length ? null : <p className="helper-text">{t('tm.saveNone')}</p>}
        {candidates.length ? <ul>{candidates.map(item => {          const reason = item.blocking_reason;
          return <li key={item.method_id}>
            <Checkbox disabled={!item.savable || save.isPending} checked={item.savable && !unchecked.includes(item.method_id)}
              onChange={checked => setUnchecked(previous => checked
                ? previous.filter(id => id !== item.method_id) : [...previous, item.method_id])}>
              <span>{item.name ?? item.method_id}</span>
              <small className="helper-text">{t('tm.saveRuleCount', { count: item.rule_count })}</small>
            </Checkbox>
            {item.savable || !reason ? null
              : <span className="helper-text">{REASONS.includes(reason) ? t(`tm.saveReason.${reason}` as never) : reason}</span>}
          </li>;
        })}</ul> : null}
      </section>
      {save.isError ? <Alert type="error" showIcon
        content={save.error instanceof Error ? save.error.message : String(save.error)} /> : null}
      <div className="form-actions">
        <Button disabled={save.isPending} onClick={onClose}>{t('workspace.draftCancel')}</Button>
        <Button type="primary" loading={save.isPending} disabled={blocked}
          onClick={() => { if (inFlight.current || blocked) return; inFlight.current = true; save.mutate(); }}>
          {t('tm.saveSubmit')}
        </Button>
      </div>
    </> : null}
  </Modal>;
}
