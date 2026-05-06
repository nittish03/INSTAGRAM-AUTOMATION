import { render, screen } from "@testing-library/react";

import { SafeModeBanner } from "@/components/safe-mode-banner";

describe("SafeModeBanner", () => {
  it("renders settings summary", () => {
    render(
      <SafeModeBanner
        settings={{
          enabled: true,
          globalPauseOutreach: false,
          pauseNewConnectionInvites: true,
          maxBulkApprove: 20,
          maxBulkExport: 40,
        }}
      />,
    );

    expect(screen.getByText("Safe Mode: Enabled")).toBeInTheDocument();
    expect(screen.getByText(/New invites paused: On/)).toBeInTheDocument();
    expect(screen.getByText(/Max bulk approve: 20/)).toBeInTheDocument();
  });
});

