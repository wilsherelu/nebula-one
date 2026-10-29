"""One projection for screen and exports of a frozen organizational user-rule answer."""
from .frozen_report import names, detail_row, contributions


def organization_user_report(result, snapshot, graph, workspace):
    processes, exchanges = names(graph,workspace)
    overlay=result['user_method_grouping']
    grouping=overlay['grouping']
    groups={'scope_1':'on_site_direct','scope_2':'purchased_energy_lifecycle','scope_3':'other_value_chain',
            'excluded':'user_excluded','unattributed':'unassigned','engine_gap':'engine_gap'}
    by_node={n['id']:n.get('process_uuid',n['id']) for n in graph.get('nodes',[])}
    terms={term['exchange_id']:term for receipt in (snapshot.get('lcia_results') or {}).get('indicator_contribution_receipts',[])
           if receipt['canonical_indicator_key']==result['climate_source']['indicator_key'] for term in receipt.get('terms',[])}
    rows=[]
    for path in grouping['paths']:
        source=terms.get(path.get('source_exchange_id'),{})
        exchange=path['exchange_id']
        process=by_node.get(exchange.split('::',1)[0],path.get('background_process_uuid'))
        decision=path['decision']
        quantity=source.get('amount')
        if isinstance(quantity,(int,float)):
            quantity *= result['activity_basis']['scale_factor'] * (path.get('path_share') if path.get('path_share') is not None else 1)
        row=detail_row(processes,exchanges,exchange,process,group=groups[decision],quantity=quantity,
            quantity_unit=source.get('amount_unit'),contribution_value=path['path_contribution_value'],
            contribution_unit=grouping['indicator_unit'],status='excluded_with_basis' if decision=='excluded' else
                'unassigned' if decision in {'unattributed','engine_gap'} else 'counted',basis=None,identity={**path,'factor':source})
        rows.append(row)
    summary=[dict(group=key,value=value['value'],unit=value['unit'],status=value['status']) for key,value in result['groups'].items()]
    for key in ('excluded','unattributed','engine_gap'):
        summary.append(dict(group=groups[key],value=grouping[key]['value'],unit=grouping['indicator_unit'],
                            status='excluded_with_basis' if key=='excluded' else 'unassigned'))
    declared={d['id']:d['name'] for d in (snapshot['provider_receipt'].get('user_calculation_method') or {}).get('reporting_dimensions',[])}
    dimensions=[dict(id=key,name=declared.get(key,key),categories=value['categories'],reconciled=value['reconciled'])
        for key,value in ((overlay.get('dimension_grouping') or {}).get('grouping') or {}).get('dimensions',{}).items() if key!='lc_scope']
    baseline=result['base_accounting']
    categories=baseline['groups']['other_value_chain']['categories']
    gaps=[dict(name=row['name'],status=row['status'],identity=row) for row in categories
          if row['category'] in baseline['coverage']['missing_categories']]
    gaps += [dict(name=exchanges.get(key,{}).get('name'),status='missing_energy_path',identity={'exchange_id':key})
             for key in baseline['coverage'].get('missing_energy_paths',[])]
    gaps += [dict(name=exchanges.get(gap.get('exchange_id'),{}).get('name'),status='unassigned',identity=gap)
             for gap in grouping['coverage_gaps']]
    uncharacterized=[detail_row(processes,exchanges,term['exchange_id'],term['process_uuid'],group='unassigned',
        quantity=term.get('amount'),quantity_unit=term.get('amount_unit'),contribution_value=None,
        contribution_unit=grouping['indicator_unit'],status='method_has_no_cf',identity=term)
        for term in result['climate_source'].get('uncharacterized_terms',[])]
    return dict(summary=summary,complete_total=result['combined_total'],details=rows,
        process_contributions=contributions(rows,{r['group']:r['value'] for r in summary}),detail_status='available',
        gaps=gaps,outside_boundary=[dict(name=row['flow_name'],status=row['status'],identity=row['identity'])
            for row in rows if row['group']=='user_excluded'],uncharacterized=uncharacterized,custom_dimensions=dimensions,
        user_rule_totals=dict(counted=result['counted_total'],known_model=result['known_model_total'],unit=grouping['indicator_unit']),
        user_method=overlay['method'])
