import type { SeedProjectTemplate } from '../../api/seedProjects';

export type TemplateContextResolution =
  | { status: 'resolved'; item: SeedProjectTemplate }
  | { status: 'ambiguous'; matches: SeedProjectTemplate[] }
  | { status: 'unresolved' };

/**
 * Resolve an old deep link to one exact template version.
 *
 * Several published versions can share one modelling source, so a link that only names the source
 * is genuinely ambiguous: the caller must offer the matches for choosing. Picking the first or the
 * newest would silently configure another template version than the reader asked for.
 */
export function resolveTemplateContext(
  items: SeedProjectTemplate[] | undefined,
  source: string | null,
  model: string | null,
  revision: string | null,
): TemplateContextResolution {
  if (!items || !source) return { status: 'unresolved' };
  const matches = items.filter(item => item.source_application_id === source
    && (!model || item.source_model_id === model)
    && (!revision || item.source_revision_id === revision));
  if (matches.length === 1) return { status: 'resolved', item: matches[0] };
  return matches.length > 1 ? { status: 'ambiguous', matches } : { status: 'unresolved' };
}
