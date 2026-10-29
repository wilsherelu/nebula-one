import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import { templateMethodsApi, type TemplateAccountingMethods } from '../api/templateMethods';
import type { CalculationMethodDetail } from '../api/types';
import { TemplateConfigPage } from './TemplateConfigPage';

afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });

it('edits a template result-category rule on its exact graph without requesting a project worksheet', async () => {
  const graph = {nodes: [{id: 'furnace', name: '高炉', inputs: [], outputs: [
    {id: 'steel', name: '钢材', unit: 'kg'},
    {id: 'co2', name: '二氧化碳', type: 'biosphere', flowUuid: 'co2-id', unit: 'kg'},
    {id: 'ch4', name: '甲烷', type: 'biosphere', flowUuid: 'ch4-id', unit: 'kg'},
  ]}], edges: []};
  const dimension = {id: 'result_category', name: '结果分类', categories: [
    {id: 'direct', name: '直接排放', is_leaf: true},
  ]};
  const detail: CalculationMethodDetail = {method: {id: 'custom', application_id: 'source',
    model_revision_id: 'exact-revision', name: '自定义排放', purpose: 'custom', description: null,
    origin_method_id: null, status: 'draft', created_at: '', updated_at: ''}, latest_version: 1,
    versions: [{id: 'v1', method_id: 'custom', version: 1, cbam_boundary_ref: null,
      content_sha256: 'a'.repeat(64), status: 'draft', created_at: '', validated_at: null, rules: [],
      semantics: 'result_category.v1', reporting_dimensions: [dimension]}]};
  const payload: TemplateAccountingMethods = {schema_version: 'nebula_one.template-accounting-methods.v1', template: {id: 'steel', title: '钢铁模板', display_name: {zh: '钢铁模板'},
    kind: 'seed', template_sha256: 'b'.repeat(64), editable: false, capabilities: [], template_profile: null,
    method_package_refs: [], unresolved_method_package_refs: [],
    version: '1.1.9', official: true, source_application_id: 'source', source_revision_id: 'exact-revision',
    source_model_id: 'model', model: {graph_snapshot: graph, process_count: 1, port_count: 3,
      graph_sha256: 'c'.repeat(64), graph_basis: 'source_revision'}}, tasks: [], other_scheme_keys: [],
    methods: [{method_key: 'source:custom@1', purpose: 'custom', method_group: 'user', origin: 'source_user_method',
      display_name: {zh: '自定义排放'}, editable: true, actions: ['edit'], base_method_ref: null,
      rule_source: {kind: 'user_method_rules', declared: [], declared_count: 0, port_count: 3,
        undeclared_port_count: 3, declared_but_absent_from_model: [], provenance: []}, coverage_gaps: [],
      check: {status: 'draft', status_basis: 'method_version_status', problem_count: 0, problems: []},
      user_method: {method_id: 'custom', version: 1, content_sha256: 'a'.repeat(64), status: 'draft',
        name: '自定义排放', description: null, origin_method_id: null, origin_method_version: null,
        model_processing_rules_ref: null, cbam_boundary_ref: null, rule_count: 0, reporting_dimension_count: 0}}]};
  vi.spyOn(templateMethodsApi, 'forTemplate').mockResolvedValue(payload);
  vi.spyOn(api, 'calculationMethod').mockResolvedValue(detail);
  const worksheet = vi.spyOn(api, 'workspace').mockRejectedValue(new ApiError('No worksheet', 422, 'PROJECT_TEMPLATE_UNAVAILABLE'));
  const save = vi.spyOn(api, 'saveCalculationMethodVersion').mockResolvedValue({...detail, latest_version: 2,
    versions: [{...detail.versions[0], version: 2}]});
  render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter initialEntries={['/templates/steel/config?method=custom']}>
      <Routes><Route path="/templates/:templateId/config" element={<TemplateConfigPage />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
  expect(await screen.findByText('甲烷', {exact: false})).toBeInTheDocument();
  expect(worksheet).not.toHaveBeenCalled();
  expect(screen.queryByText('PROJECT_TEMPLATE_UNAVAILABLE')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', {name: '新建项目'})).not.toBeInTheDocument();
  const row = screen.getByText('二氧化碳', {exact: false}).closest('tr')!;
  await userEvent.click(within(row).getByRole('combobox', {name: '结果分类'}));
  fireEvent.click(await screen.findByRole('option', {name: '直接排放'}));
  await waitFor(() => expect(screen.getByRole('button', {name: '保存为新版本'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button', {name: '保存为新版本'}));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][2]).toMatchObject({expected_content_sha256: 'a'.repeat(64),
    rules: [expect.objectContaining({process_instance_id: 'furnace', exchange_id: 'furnace::co2', boundary_status: 'selected',
      categories: {result_category: 'direct'}})]});
});
