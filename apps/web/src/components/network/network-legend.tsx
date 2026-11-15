/** What each symbol means. States are told apart by shape and dash, never by colour alone. */
export function NetworkLegend() {
  const item = "flex items-center gap-2";
  return (
    <section aria-labelledby="network-legend-title" className="mt-3 text-xs text-muted">
      <h3 id="network-legend-title" className="sr-only">
        Legend
      </h3>
      <ul className="flex flex-wrap gap-x-5 gap-y-2">
        <li className={item}>
          <svg aria-hidden="true" width="26" height="10">
            <rect x="1" y="2" width="24" height="6" className="fill-ink" />
          </svg>
          Bus
        </li>
        <li className={item}>
          <svg aria-hidden="true" width="26" height="10">
            <path d="M 1 5 L 25 5" className="stroke-ink" strokeWidth="2" />
          </svg>
          Line
        </li>
        <li className={item}>
          <svg aria-hidden="true" width="26" height="16">
            <circle cx="9" cy="8" r="6" className="stroke-ink fill-panel" />
            <circle cx="16" cy="8" r="6" className="stroke-ink" fill="none" />
          </svg>
          Transformer
        </li>
        <li className={item}>
          <svg aria-hidden="true" width="14" height="14">
            <rect x="2" y="2" width="10" height="10" className="stroke-ink fill-ink" />
          </svg>
          Switch, model position closed
        </li>
        <li className={item}>
          <svg aria-hidden="true" width="14" height="14">
            <rect
              x="2"
              y="2"
              width="10"
              height="10"
              className="stroke-ink fill-panel"
              strokeWidth="1.5"
            />
          </svg>
          Switch, model position open
        </li>
        <li className={item}>
          <svg aria-hidden="true" width="16" height="14">
            <path d="M 2 3 L 14 3 L 8 12 Z" className="stroke-ink fill-panel" />
          </svg>
          Load
        </li>
        <li className={item}>
          <svg aria-hidden="true" width="16" height="16">
            <circle cx="8" cy="8" r="6" className="stroke-ink fill-panel" />
          </svg>
          Generator
        </li>
        <li className={item}>
          <svg aria-hidden="true" width="16" height="16">
            <rect x="2" y="2" width="12" height="12" className="stroke-ink fill-panel" />
            <path d="M 2 2 L 14 14 M 14 2 L 2 14" className="stroke-ink" />
          </svg>
          External grid
        </li>
        <li className={item}>
          <svg aria-hidden="true" width="26" height="10">
            <path d="M 1 5 L 25 5" className="stroke-muted" strokeWidth="2" strokeDasharray="5 4" />
          </svg>
          Out of service (dashed)
        </li>
      </ul>
    </section>
  );
}
