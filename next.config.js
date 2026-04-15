/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    outputFileTracingIncludes: {
      '/api/runs': ['./data/**'],
    },
  },
};
module.exports = nextConfig;
