import { useId, useState, type ReactNode } from "react";
import s from "./Term.module.css";

// An explained term: hover, focus or tap shows a short definition. Escape hides it.
export function Term({ children, tip }: { children: ReactNode; tip: string }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className={s.wrap} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className={s.term} aria-describedby={id} aria-expanded={open}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={() => setOpen(true)}
        onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>
        {children}
      </button>
      <span role="tooltip" id={id} className={s.tip} data-open={open || undefined}>{tip}</span>
    </span>
  );
}
