import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const backend = process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000";
    return [
      // Used only for the Google OAuth start (which needs a top-level redirect to Google).
      { source: "/oauth/google/start", destination: `${backend}/admin/google/auth/start/` },
      { source: "/oauth/google/disconnect", destination: `${backend}/admin/google/auth/disconnect/` },
    ];
  },
};

export default nextConfig;
