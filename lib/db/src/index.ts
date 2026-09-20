import { drizzle } from "drizzle-orm/node-postgres";
import pg from "pg";
import * as schema from "./schema";

const { Pool } = pg;

// Keep module loading deterministic when the database is not provisioned; reads
// will fail with a normal connection error and the API can return 503.
export const pool = new Pool({
  connectionString: process.env.DATABASE_URL ?? "postgresql://invalid:invalid@127.0.0.1:1/invalid",
});
export const db = drizzle(pool, { schema });

export * from "./schema";
