import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/diagnostics/:path*",
        destination: `${process.env.COACHLENS_API_ORIGIN ?? "http://127.0.0.1:8000"}/diagnostics/:path*`,
      },
      {
        source: "/api/designs/:path*",
        destination: `${process.env.COACHLENS_API_ORIGIN ?? "http://127.0.0.1:8000"}/designs/:path*`,
      },
    ];
  },
};

export default nextConfig;
