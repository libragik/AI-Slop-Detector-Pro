import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  serverExternalPackages: ["@contentauth/c2pa-node"],
  devIndicators: false,
};

export default nextConfig;
