import { ICON_PATHS } from '@/lib/icons';

/** A stroke icon; markup comes only from the constant ICON_PATHS table. */
export function Icon({ name, size = 18, className }: { name: string; size?: number; className?: string }) {
  const path = ICON_PATHS[name] || ICON_PATHS.dot;
  return (
    <span className={'icon' + (className ? ' ' + className : '')} aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" dangerouslySetInnerHTML={{ __html: path }} />
    </span>
  );
}
