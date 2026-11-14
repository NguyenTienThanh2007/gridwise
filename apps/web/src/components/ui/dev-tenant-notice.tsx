/**
 * Shown wherever tenant data appears. The grid and simulation APIs exist only in local and
 * test environments and act for one fixed development organisation configured on the
 * server (decisions 0008, 0009, 0013). That is not sign-in, and not access control.
 */
export function DevTenantNotice() {
  return (
    <p className="mb-4 max-w-3xl rounded border border-line bg-panel px-3 py-2 text-xs text-muted">
      <span className="font-medium text-ink">Development mode.</span> There is no sign-in: this
      build acts for one fixed development organisation configured on the server. It is not access
      control and must not be exposed beyond this machine.
    </p>
  );
}
