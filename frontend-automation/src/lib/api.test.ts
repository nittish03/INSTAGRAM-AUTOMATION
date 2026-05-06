import { api } from "@/lib/api";

describe("api client", () => {
  it("calls workbench endpoint", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      text: async () =>
        JSON.stringify({
          ok: true,
          stats: {
            connectedDeals: 1,
            draftsAwaitingApproval: 2,
            failedTasks: 0,
            pendingTasks: 4,
            stalePendingDeals: 0,
            connectedWithoutExport: 1,
            connectedAwaitingVerification: 0,
            connectedWithoutFollowup: 1,
            actions24h: 3,
          },
          inbox: [],
        }),
      redirected: false,
      status: 200,
    }) as unknown as typeof fetch;

    const data = await api.workbench();
    expect(data.stats.connectedDeals).toBe(1);
    expect(fetch).toHaveBeenCalledWith(
      "/api/backend/api/workbench",
      expect.objectContaining({
        credentials: "include",
        cache: "no-store",
      }),
    );
  });
});

