import { useEffect, useState } from 'react';

/** Whether the viewport is at or below `maxWidth` px, tracked live so a layout that must not scroll
 * sideways can drop its wide-table form instead of only looking right at the initial width. */
export function useNarrowViewport(maxWidth = 767): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.innerWidth <= maxWidth);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia(`(max-width: ${maxWidth}px)`);
    const update = () => setNarrow(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, [maxWidth]);
  return narrow;
}
