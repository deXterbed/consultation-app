import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export", // This exports static HTML/JS files
  trailingSlash: true, // Export pages as dirs (product/index.html) for static servers
  images: {
    unoptimized: true, // Required for static export
  },
};

export default nextConfig;
