/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    // Listings embed images from many source CDNs; allow any host.
    remotePatterns: [{ protocol: "https", hostname: "**" }],
  },
  experimental: {
    typedRoutes: false,
  },
};

export default nextConfig;
