import { Auth0Client } from "@auth0/nextjs-auth0/server";

export const auth0 = new Auth0Client({
  domain: process.env.AUTH0_DOMAIN ?? "your-tenant.us.auth0.com",
  clientId: process.env.AUTH0_CLIENT_ID ?? "your_client_id",
  clientSecret: process.env.AUTH0_CLIENT_SECRET ?? "your_client_secret",
  appBaseUrl: process.env.APP_BASE_URL ?? process.env.AUTH0_BASE_URL ?? "http://localhost:3000",
});
