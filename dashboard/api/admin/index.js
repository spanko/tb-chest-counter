const { getPool } = require("../shared/db");

// Minimal admin endpoint for testing
module.exports = async function (context, req) {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    context.res = {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Admin-Code"
      },
      body: ""
    };
    return;
  }

  // Check admin authorization
  const adminCode = req.headers["x-admin-code"];
  if (adminCode !== "FOR2026-ADMIN") {
    context.res = {
      status: 403,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
      body: JSON.stringify({ error: "Unauthorized" })
    };
    return;
  }

  const action = req.query.action || "status";

  try {
    const pool = getPool();

    // Simple test query
    const result = await pool.query("SELECT 1 as test");

    context.res = {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
      body: JSON.stringify({
        status: "admin endpoint working",
        action: action,
        dbTest: result.rows[0].test,
        timestamp: new Date().toISOString()
      })
    };
  } catch (err) {
    context.log.error("Admin API error:", err.message);
    context.res = {
      status: 500,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
      },
      body: JSON.stringify({ error: "Database error", detail: err.message })
    };
  }
};
