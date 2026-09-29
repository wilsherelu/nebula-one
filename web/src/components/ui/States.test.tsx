import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { ErrorState } from './States';

afterEach(() => {
  cleanup();
});

describe('Error state', () => {
  it('keeps the stable error code and backend details visible next to the message', () => {
    render(<ErrorState error={new ApiError(
      '已固定版本的方法包未声明本实现使用的 Scope 1 计算合同。',
      409,
      'GHG_INVENTORY_CALCULATION_CONTRACT_UNSUPPORTED',
      { required_contract: 'scope1_period_scaling.v1', declared_contract: null },
    )} />);

    expect(screen.getByText('已固定版本的方法包未声明本实现使用的 Scope 1 计算合同。')).toBeInTheDocument();
    expect(screen.getByText(/GHG_INVENTORY_CALCULATION_CONTRACT_UNSUPPORTED/)).toBeInTheDocument();
    expect(screen.getByText(/scope1_period_scaling\.v1/)).toBeInTheDocument();
  });

  it('still renders a plain failure without a code or details', () => {
    render(<ErrorState error={new Error('连接中断')} />);
    expect(screen.getByText('连接中断')).toBeInTheDocument();
    expect(screen.queryByText(/错误码/)).not.toBeInTheDocument();
  });

  it('reads a dependency gap as what is missing, what it blocks and how to fix it', () => {
    render(<ErrorState error={new ApiError('该请求缺一份精确上游数据。', 422, 'CARBON_DIRECT_EMISSION_REQUIRED', {
      dependency_gap: {
        schema_version: 'nebula_one.dependency-gap.v1',
        code: 'CARBON_DIRECT_EMISSION_REQUIRED',
        what_missing: {
          kind: 'direct_emission_exchange',
          required_identity: { flow_identities: ['tiangong_open_data/08a91e70-3ddc-11dd-923d-0050c2490048/03.00.004'] },
          observed_identity: { flow_identities: [] },
        },
        affects: { step: 'carbon_management', downstream_steps: ['organization_ghg_inventory'], scopes_affected: ['scope_1'], results_produced: false },
        how_to_resolve: [{ action: '重新冻结带直接排放端口的快照', owner: '建模与引擎求解', precondition: '端口排放流身份与方法包一致' }],
        evidence: { method_package_ref: 'carbon.management.ef31.period@1.1.0' },
      },
    })} />);

    const notice = screen.getByRole('note', { name: '缺数据说明' });
    expect(within(notice).getByText('缺什么')).toBeInTheDocument();
    expect(within(notice).getByText(/direct_emission_exchange/)).toBeInTheDocument();
    expect(within(notice).getByText(/08a91e70-3ddc-11dd-923d-0050c2490048/)).toBeInTheDocument();
    expect(within(notice).getByText(/计算步骤 carbon_management/)).toBeInTheDocument();
    expect(within(notice).getByText(/连带受阻 organization_ghg_inventory/)).toBeInTheDocument();
    // an empty observed list reads as 无, never as a number
    expect(within(notice).getByText(/当前观测：flow_identities=无/)).toBeInTheDocument();
    expect(within(notice).getByText(/重新冻结带直接排放端口的快照/)).toBeInTheDocument();
  });

  it('names the references a period-chain refusal could not resolve', () => {
    render(<ErrorState error={new ApiError('期间观测无法精确解析。', 409, 'PERIOD_ENERGY_PERIOD_SET_MISMATCH', {
      dependency_gap: {
        schema_version: 'nebula_one.dependency-gap.v1',
        code: 'PERIOD_ENERGY_PERIOD_SET_MISMATCH',
        what_missing: {
          kind: 'reporting_period',
          requested_ids: ['a-period-nobody-created', 'period-a'],
          unresolved_ids: ['a-period-nobody-created'],
          observed_identity: { reporting_period_ids_of_this_application: ['period-a', 'period-b'] },
        },
        affects: { step: 'period_energy_trend', downstream_steps: ['organization_ghg_inventory'], scopes_affected: [], results_produced: false },
        how_to_resolve: [{ action: '先为该应用建立缺失的报告期', owner: '应用配置 / seed 自动加载', precondition: '报告期属于本应用' }],
        evidence: { application_id: 'application-1' },
      },
    })} />);

    const notice = screen.getByRole('note', { name: '缺数据说明' });
    expect(within(notice).getByText(/解析不到的引用：a-period-nobody-created/)).toBeInTheDocument();
    expect(within(notice).getByText(/未指明范围/)).toBeInTheDocument();
    // the refusal produces nothing, so the notice has to keep saying so
    expect(within(notice).getByText(/本次没有产出任何结果/)).toBeInTheDocument();
  });

  it('leaves an error whose gap payload is not the pinned version untouched', () => {
    render(<ErrorState error={new ApiError('x', 409, 'SOMETHING_ELSE', {
      dependency_gap: { schema_version: 'nebula_one.dependency-gap.v2', code: 'SOMETHING_ELSE' },
    })} />);
    expect(screen.queryByRole('note', { name: '缺数据说明' })).not.toBeInTheDocument();
    expect(screen.getByText(/错误码：SOMETHING_ELSE/)).toBeInTheDocument();
  });

  it('leads with the unverified background mapping and keeps the engine identity in 技术详情', () => {
    const unresolved = 'b32061b1-8d24-4663-b10d-0a1c705f2937';
    render(<ErrorState error={new ApiError(
      '背景排放流映射待核实：所选背景过程仍有排放流没有已审定的身份映射，本次计算没有产生结果。',
      422,
      'PROJECT_BACKGROUND_ELEMENTARY_MAPPING_UNVERIFIED',
      {
        upstream_code: 'MAPPED_BACKGROUND_ELEMENTARY_MAPPING_NOT_FOUND',
        upstream_detail: { code: 'MAPPED_BACKGROUND_ELEMENTARY_MAPPING_NOT_FOUND', details: { ecoinvent_flow_uuid: unresolved } },
        dependency_gap: {
          schema_version: 'nebula_one.dependency-gap.v1',
          code: 'MAPPED_BACKGROUND_ELEMENTARY_MAPPING_NOT_FOUND',
          what_missing: {
            kind: 'background_elementary_mapping',
            required_identity: '当前计算路径所需的背景排放流身份映射尚未通过核验',
          },
          affects: { step: 'provider_solve', downstream_steps: ['mfa', 'pcf', 'cbam'], scopes_affected: ['所选背景过程的上游排放'], results_produced: false },
          how_to_resolve: [{ action: '由 Nebula LCA 一次性审计并补齐该背景过程全部排放流的身份映射与方法覆盖，再重算', owner: 'Nebula LCA 来源侧', precondition: '映射包或认证裁决包收录该流' }],
          evidence: { unresolved_elementary_flows: { ecoinvent_flow_uuid: unresolved } },
        },
      },
    )} />);

    const notice = screen.getByRole('note', { name: '缺数据说明' });
    expect(within(notice).getByText(/background_elementary_mapping/)).toBeInTheDocument();
    expect(within(notice).getByText(/本次没有产出任何结果/)).toBeInTheDocument();
    expect(within(notice).getByText(/由 Nebula LCA 一次性审计/)).toBeInTheDocument();
    // the unresolved flow identity is technical evidence, so it never competes with the explanation
    expect(within(notice).queryByText(new RegExp(unresolved))).not.toBeInTheDocument();
    const disclosure = screen.getByText('技术详情').closest('details')!;
    const identities = screen.getAllByText(new RegExp(unresolved));
    expect(identities).toHaveLength(1);
    expect(identities[0].closest('details')).toBe(disclosure);
    const code = screen.getByText(/错误码：PROJECT_BACKGROUND_ELEMENTARY_MAPPING_UNVERIFIED/);
    expect(code.closest('details')).toBe(disclosure);
    expect(within(disclosure).getByText(/MAPPED_BACKGROUND_ELEMENTARY_MAPPING_NOT_FOUND/)).toBeInTheDocument();
  });
});
