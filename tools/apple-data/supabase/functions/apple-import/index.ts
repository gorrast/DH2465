import { createHandler } from "./core.mjs";

Deno.serve((request: Request) => createHandler(Deno.env.toObject())(request));
