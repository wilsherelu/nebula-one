import { Alert, Button, Select, Tag, Tooltip } from '@arco-design/web-react';
import { IconArrowRight, IconInfoCircle, IconPlus } from '@arco-design/web-react/icon';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { CaseCatalogTable, caseDemandLabel, matchCaseApplication } from '../components/CaseCatalogTable';
import { CasePackAuditDrawer } from '../components/CasePackAuditDrawer';
import { PageHeader } from '../components/ui/PageHeader';
import { StatusBadge } from '../components/ui/StatusBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/ui/States';

export function CasePacksPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [auditVisible, setAuditVisible] = useState(false);
  const [drawerTab, setDrawerTab] = useState('application');
  const catalog = useQuery({ queryKey: ['casepacks'], queryFn: api.casepacks });
  const setup = useQuery({ queryKey: ['setup-status'], queryFn: api.setupStatus });
  const capabilityCatalog = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities });
  const applications = useQuery({ queryKey: ['applications'], queryFn: () => api.applications() });
  const selectedPackId = searchParams.get('pack') ?? '';
  const selectedCaseId = searchParams.get('case') ?? '';
  const selectedModuleKey = searchParams.get('module') ?? '';
  const selectedPack = catalog.data?.items.find((item) => item.id === selectedPackId) ?? catalog.data?.items[0];
  const selectedCase = selectedPack?.applications.find((item) => item.id === selectedCaseId) ?? selectedPack?.applications[0];
  const materializedApplication = selectedPack && selectedCase
    ? matchCaseApplication(selectedPack, selectedCase, applications.data ?? []) : undefined;
  const workbenchPath = (applicationId: string, caseId: string, moduleKey = '') => {
    const params = new URLSearchParams({ case: caseId });
    if (moduleKey) params.set('module', moduleKey);
    return `/applications/${applicationId}/workbench?${params}`;
  };
  const materialize = useMutation({
    mutationFn: (selection: {
      casePackId: string; casePackVersion: string; casePackSha256: string;
      applicationCaseId: string; applicationCaseVersion: string; resolvedCaseSha256: string;
      moduleKey: string;
    }) => {
      return api.materializeCasePack(
        selection.casePackId,
        selection.casePackVersion,
        selection.applicationCaseId,
        selection.applicationCaseVersion,
        {
          expected_case_pack_sha256: selection.casePackSha256,
          expected_resolved_case_sha256: selection.resolvedCaseSha256,
        },
      );
    },
    onSuccess: (result, selection) => {
      queryClient.setQueryData(['applications'], (current: typeof applications.data) => {
        const items = current ?? [];
        return items.some((item) => item.id === result.application.id)
          ? items
          : [result.application, ...items];
      });
      navigate(workbenchPath(result.application.id, selection.applicationCaseId, selection.moduleKey));
    },
  });
  const materializeSelected = () => {
    if (!selectedPack || !selectedCase || materialize.isPending || applications.isError) return;
    materialize.mutate({
      casePackId: selectedPack.id,
      casePackVersion: selectedPack.version,
      casePackSha256: selectedPack.case_pack_sha256,
      applicationCaseId: selectedCase.id,
      applicationCaseVersion: selectedCase.version,
      resolvedCaseSha256: selectedCase.resolved_case_sha256,
      moduleKey: selectedModuleKey,
    });
  };
  const capabilityRows = useMemo(() => {
    if (!selectedPack) return [];
    const keys = new Set(selectedPack.applications.flatMap((item) => [
      ...item.capabilities,
      ...item.blocked_capabilities.map((blocked) => blocked.capability),
    ]));
    const descriptors = capabilityCatalog.data?.items ?? [];
    const ordered = descriptors.filter((item) => keys.has(item.key)).map((item) => ({ ...item, registered: true }));
    const described = new Set(ordered.map((item) => item.key));
    return [
      ...ordered,
      ...Array.from(keys).filter((key) => !described.has(key)).sort().map((key) => ({
        key,
        name: key,
        execution: 'unknown',
        basis: '',
        limits: [],
        status: 'unavailable' as const,
        registered: false,
      })),
    ];
  }, [capabilityCatalog.data?.items, selectedPack]);

  useEffect(() => {
    if (!selectedPack || !selectedCase) return;
    if (selectedPackId === selectedPack.id && selectedCaseId === selectedCase.id) return;
    const next = new URLSearchParams(searchParams);
    next.set('pack', selectedPack.id);
    next.set('case', selectedCase.id);
    setSearchParams(next, { replace: true });
  }, [searchParams, selectedCase, selectedCaseId, selectedPack, selectedPackId, setSearchParams]);

  const selectPack = (id: string) => {
    materialize.reset();
    const pack = catalog.data?.items.find((item) => item.id === id);
    const next = new URLSearchParams(searchParams);
    next.set('pack', id);
    if (pack?.applications[0]) next.set('case', pack.applications[0].id);
    next.delete('module');
    setSearchParams(next);
  };
  const selectCase = (id: string) => {
    materialize.reset();
    const next = new URLSearchParams(searchParams);
    next.set('case', id);
    if (id !== selectedCaseId) next.delete('module');
    setSearchParams(next);
    setDrawerTab('application');
    setAuditVisible(true);
  };
  const selectShowcaseModule = (moduleKey: string, applicationCaseId: string) => {
    if (!selectedPack) return;
    const targetCase = selectedPack.applications.find((item) => item.id === applicationCaseId);
    if (!targetCase) return;
    const targetApplication = matchCaseApplication(selectedPack, targetCase, applications.data ?? []);
    if (targetApplication) {
      navigate(workbenchPath(targetApplication.id, targetCase.id, moduleKey));
      return;
    }
    const next = new URLSearchParams(searchParams);
    next.set('case', targetCase.id);
    next.set('module', moduleKey);
    setSearchParams(next);
    materialize.reset();
    setDrawerTab('application');
    setAuditVisible(true);
  };

  if (catalog.isLoading) return <main className="app-page"><PageHeader title="案例库" description="选择一个已验证案例，查看适用的分析任务。" /><section className="section-panel"><LoadingState rows={6} /></section></main>;
  if (catalog.isError) return <main className="app-page"><PageHeader title="案例库" description="选择一个已验证案例，查看适用的分析任务。" /><ErrorState error={catalog.error} onRetry={() => catalog.refetch()} /></main>;
  if (!catalog.data?.items.length) {
    const message = catalog.data?.issues[0]?.message;
    return <main className="app-page"><PageHeader title="案例库" description="选择一个已验证案例，查看适用的分析任务。" /><section className="section-panel">{message ? <ErrorState error={new Error('案例目录暂不可用，请检查服务端目录配置。')} onRetry={() => catalog.refetch()} /> : <EmptyState description="尚未配置可用案例" />}</section></main>;
  }
  if (!selectedPack || !selectedCase) return null;

  return (
    <main className="app-page catalog-page">
      <PageHeader title="案例库" description="选择案例，开始分析。" action={<Button size="small" icon={<IconInfoCircle />} disabled={materialize.isPending} onClick={() => { setDrawerTab('case'); setAuditVisible(true); }}>审计证据</Button>} />
      {setup.isError ? (
        <Alert type="warning" title="启动状态暂不可用" content="案例目录仍可使用；求解前请重新检查服务连接。" action={<Button size="small" onClick={() => setup.refetch()}>重新检查</Button>} />
      ) : setup.data?.provider.status === 'unavailable' ? (
        <Alert type="warning" title="算法服务尚未连接" content={`${setup.data.provider.message}${setup.data.provider.remediation ? ` ${setup.data.provider.remediation}` : ''}`} />
      ) : null}
      {catalog.data.issues.length ? <Alert type="warning" title="部分案例未能载入" content="可用案例不受影响，详细原因请联系维护人员检查目录配置。" /> : null}
      <section className="catalog-surface" aria-label="案例目录">
        <div className="catalog-pack">
          <label htmlFor="casepack-select">案例包</label>
          {catalog.data.items.length > 1 ? <Select id="casepack-select" disabled={materialize.isPending} value={selectedPack.id} onChange={selectPack} options={catalog.data.items.map((item) => ({ value: item.id, label: item.title }))} /> : <strong>{selectedPack.title}</strong>}
          <Tag>v{selectedPack.version}</Tag>
        </div>
        {selectedPack.showcase?.modules.length ? <nav className="catalog-shortcuts" aria-label="分析快捷入口">
          <span className="helper-text">快速进入</span>
          {selectedPack.showcase.modules.map((module) => <Tooltip key={module.key} content={module.description} trigger={['hover', 'focus']}>
            <Button type="text" size="small" aria-pressed={module.key === selectedModuleKey} disabled={!selectedPack.applications.some((item) => item.id === module.application_case_id) || applications.isLoading || applications.isError || materialize.isPending} onClick={() => selectShowcaseModule(module.key, module.application_case_id)}>{module.title}<IconArrowRight /></Button>
          </Tooltip>)}
        </nav> : null}
        {applications.isError ? <ErrorState error={applications.error} onRetry={() => applications.refetch()} /> : null}
        <CaseCatalogTable key={selectedPack.id} pack={selectedPack} applications={applications.data ?? []} checking={applications.isLoading} unavailable={applications.isError} pending={materialize.isPending} selectedCaseId={selectedCase.id} onDetails={selectCase} onOpen={(item, application) => application ? navigate(workbenchPath(application.id, item.id, item.id === selectedCaseId ? selectedModuleKey : '')) : selectCase(item.id)} />
      </section>
      <CasePackAuditDrawer casepack={selectedPack} applicationCase={selectedCase} visible={auditVisible} initialTab={drawerTab} onClose={() => { if (!materialize.isPending) setAuditVisible(false); }} action={<Button type="primary" icon={materializedApplication ? <IconArrowRight /> : <IconPlus />} loading={materialize.isPending} disabled={applications.isLoading || applications.isError || materialize.isPending} onClick={() => materializedApplication ? navigate(workbenchPath(materializedApplication.id, selectedCase.id, selectedModuleKey)) : materializeSelected()}>{materializedApplication ? '进入分析' : '创建分析'}</Button>} summary={<>
        <h3 className="catalog-study-title">{selectedCase.study_frame_title}</h3>
        <dl className="catalog-study-facts"><div><dt>核算规模</dt><dd>{caseDemandLabel(selectedCase)}</dd></div><div><dt>研究框架</dt><dd><StatusBadge status={selectedCase.study_frame_status} /></dd></div></dl>
        {materialize.isError ? <ErrorState error={materialize.error} onRetry={materializeSelected} /> : null}
      </>} details={<>
          {selectedPack.system_summary ? (
            <section className="casepack-system" aria-labelledby="casepack-system-title">
              <div className="section-heading">
                <div><span className="helper-text">冻结模型快照</span><h3 id="casepack-system-title">System 基线</h3></div>
                <Tag>{selectedPack.system_summary.functional_unit}</Tag>
              </div>
              <dl className="casepack-system__metrics">
                <div><dt>Process</dt><dd>{selectedPack.system_summary.process_count}</dd></div>
                <div><dt>Flow</dt><dd>{selectedPack.system_summary.flow_count}</dd></div>
                <div><dt>内部连接</dt><dd>{selectedPack.system_summary.connection_count}</dd></div>
                <div><dt>基本流</dt><dd>{selectedPack.system_summary.elementary_flow_count}</dd></div>
              </dl>
              <div className="casepack-process-list" aria-label="System Process">
                {selectedPack.system_summary.processes.map((process) => (
                  <span key={process.id}><Tag>{process.name}</Tag></span>
                ))}
              </div>
              <div className="casepack-flow-sources">
                {selectedPack.system_summary.flow_sources.map((source) => (
                  <span key={source.source_namespace}><strong>{source.flow_count}</strong> Flow · {source.source_namespace}</span>
                ))}
              </div>
            </section>
          ) : <Alert type="info" content="该案例使用远程模型 pin，目录中不包含可公开展示的 System 摘要。" />}
          <section className="casepack-capability" aria-labelledby="casepack-capability-title">
            <div className="section-heading"><div><span className="helper-text">同一 System，不同分析入口</span><h3 id="casepack-capability-title">能力覆盖</h3></div></div>
            {capabilityCatalog.isError ? <Alert type="warning" content="能力运行状态暂不可用；案例声明仍按冻结 CasePack 显示。" /> : null}
            <div className="casepack-capability__scroll" tabIndex={0} aria-label="能力覆盖表滚动区域">
              <table>
                <thead><tr><th scope="col">分析能力</th>{selectedPack.applications.map((item) => <th scope="col" key={item.id}>{item.title}</th>)}</tr></thead>
                <tbody>
                  {capabilityRows.map((capability) => (
                    <tr key={capability.key}>
                      <th scope="row"><strong>{capability.name}</strong><small>{capability.key}</small></th>
                      {selectedPack.applications.map((item) => {
                        const blocked = item.blocked_capabilities.find((entry) => entry.capability === capability.key);
                        const included = item.capabilities.includes(capability.key);
                        return <td key={item.id}>{blocked ? <Tooltip content={blocked.reason}><Tag color="red">已阻断</Tag></Tooltip> : included ? <Tag color={!capability.registered ? 'gray' : capability.status === 'ready' ? 'green' : 'orange'}>{!capability.registered ? '已声明' : capability.status === 'ready' ? '已覆盖' : '引擎不可用'}</Tag> : <span className="casepack-capability__empty">未纳入</span>}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
      </>} />
    </main>
  );
}
