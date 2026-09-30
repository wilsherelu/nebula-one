import {Alert, Button, Checkbox, Modal, Radio} from '@arco-design/web-react';
import {useMutation, useQuery} from '@tanstack/react-query';
import {useEffect, useState} from 'react';
import {api, ApiError, isStaleDataVersion} from '../api/client';
import {seedProjectsApi} from '../api/seedProjects';
import type {ProjectWorkspace} from '../api/types';
import {useI18n} from '../i18n';
import {EmptyState, ErrorState, LoadingState} from './ui/States';

export function MappedBackgroundDialog({workspace, consumerId, onClose, onSaved, onReload, embedded = false, onBusyChange}: {
  workspace: ProjectWorkspace; consumerId: string; onClose: () => void; onSaved: (next: ProjectWorkspace) => void; onReload: () => void;
  embedded?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const { lang, t, formatNumber } = useI18n();
  const [selected, setSelected] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const catalog = useQuery({queryKey: ['mapped-background', workspace.application_id, workspace.revision_id, consumerId],
    queryFn: () => seedProjectsApi.mappedCandidates(workspace.application_id, workspace.revision_id, consumerId), retry: false, staleTime: Infinity});
  const port = workspace.background_ports?.find(p => p.exchange_id === consumerId);
  const save = useMutation({mutationFn: async (remove: boolean) => {
    const other = (workspace.mapped_background_process_pins ?? []).filter(p => p.consumer_exchange_id !== consumerId);
    const resolved = remove ? undefined : await seedProjectsApi.resolveMapped(workspace.application_id, workspace.revision_id, {
      consumer_exchange_id: consumerId, process_uuid: selected, expected_mapping_package_hash: catalog.data!.mapping.package_hash, confirmed,
    });
    return api.saveProjectInputs(workspace.application_id, {
      revision_id: workspace.revision_id, expected_content_sha256: workspace.content_sha256,
      amounts: workspace.demand.map(d => d.amount), values: Object.fromEntries(workspace.fields.map(f => [f.key, f.value])),
      source: workspace.source, demand_mode: workspace.demand_mode,
      background_process_pins: (workspace.background_process_pins ?? []).filter(p => remove || p.consumer_exchange_id !== consumerId),
      project_background_pins: (workspace.project_background_pins ?? []).filter(p => remove || p.consumer_exchange_id !== consumerId),
      mapped_background_process_pins: resolved ? [...other, resolved.pin] : other,
    }, lang);
  }, onSuccess: next => {onSaved(next); onClose();}});
  useEffect(() => { onBusyChange?.(save.isPending); }, [onBusyChange, save.isPending]);
  const eligible = catalog.data?.providers.some(p => p.process_uuid === selected && p.executable)
    && (!catalog.data?.requires_confirmation || confirmed);
  const content = <>
    <div className="background-picker-body">
    {!embedded ? <p>{port?.process} · {port?.label}</p> : null}
    {catalog.isLoading ? <LoadingState /> : catalog.error instanceof ApiError && catalog.error.code === 'PROJECT_MAPPING_UNAVAILABLE' ? <><EmptyState description={t('background.empty')} /><p className="helper-text">{t('background.mappingMissing')}</p></> : catalog.isError ? <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} /> : catalog.data ? <>
      {!catalog.data.providers.length ? <><EmptyState description={t('background.empty')} /><p className="helper-text">{t('background.emptyReason')}</p></> :
        <Radio.Group value={selected} disabled={save.isPending} className="template-options" onChange={value => {setSelected(value); setConfirmed(false); save.reset();}}>
          {catalog.data.providers.map(p => <Radio key={p.process_uuid} value={p.process_uuid} disabled={!p.executable}>
            <strong>{p.process_name}</strong><p>{p.location} · {t('background.release', { release: p.database_release ?? t('background.releaseMissing') })}</p>
            {!p.executable ? <small>{t('background.notExecutable')}</small> : null}
          </Radio>)}
        </Radio.Group>}
      {catalog.data.requires_confirmation ? <Checkbox checked={confirmed} disabled={!selected || save.isPending} onChange={setConfirmed}>{t('background.confirm')}</Checkbox> : null}
      {selected ? <details><summary>{t('results.details')}</summary>{t('background.conversion', { source: catalog.data.mapping.source_unit, factor: formatNumber(catalog.data.mapping.amount_factor), target: catalog.data.mapping.target_unit, reason: catalog.data.mapping.mapping_reason })}<p>{t('background.scopeNote')}</p></details> : null}
    </> : null}
    {(workspace.mapped_background_process_pins ?? []).some(p => p.consumer_exchange_id === consumerId) ? <Button disabled={save.isPending} onClick={() => save.mutate(true)}>{t('background.remove')}</Button> : null}
    {save.isError ? <ErrorState error={save.error} onRetry={isStaleDataVersion(save.error) ? onReload : undefined} /> : null}
    </div><div className="background-picker-footer"><Button disabled={save.isPending} onClick={onClose}>{t('background.cancel')}</Button><Button type="primary" disabled={!eligible || save.isPending} loading={save.isPending} onClick={() => save.mutate(false)}>{t('background.linkConfirm')}</Button></div>
  </>;
  return embedded ? content : <Modal visible title={t('background.choose')} className="background-picker" footer={null} onCancel={() => {if (!save.isPending) onClose();}} closable={!save.isPending} maskClosable={!save.isPending} escToExit={!save.isPending} style={{width: 720, maxWidth: 'calc(100vw - 32px)'}}>{content}</Modal>;
}
