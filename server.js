const express = require('express');
const { Pool } = require('pg');
const cors = require('cors');
const path = require('path');
require('dotenv').config();

const app = express();

// Middleware
app.use(cors());
app.use(express.json({ limit: '10mb' })); // Allows large GeoJSON shapes

// PostgreSQL Database Connection
const pool = new Pool({
    user: process.env.DB_USER || 'postgres',
    host: process.env.DB_HOST || 'localhost',
    database: process.env.DB_NAME || 'spatial_db',
    password: process.env.DB_PASSWORD || 'your_db_password',
    port: process.env.DB_PORT || 5432,
});

// Admin Password for saving/clearing map state
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "pam123";

// Authentication Middleware
function authenticate(req, res, next) {
    const authHeader = req.headers['authorization'];
    if (authHeader && authHeader === `Bearer ${ADMIN_PASSWORD}`) {
        next();
    } else {
        res.status(401).json({ error: "Unauthorized: Invalid Password" });
    }
}

// -------------------------------------------------------------
// 1. SERVE FRONTEND (warning.html)
// -------------------------------------------------------------

// Serve warning.html when visitors hit the root URL
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'warning.html'));
});

// Serve static assets if you have local CSS/JS files in the same folder
app.use(express.static(__dirname));

// -------------------------------------------------------------
// 2. API ENDPOINTS (Map Data Operations)
// -------------------------------------------------------------

// GET /api/shapes (PUBLIC - Anyone can view saved map features)
app.get('/api/shapes', async (req, res) => {
    try {
        const result = await pool.query('SELECT geojson FROM map_shapes ORDER BY id ASC');
        
        // Combine features into a single GeoJSON FeatureCollection
        const features = result.rows.map(row => row.geojson);
        const featureCollection = {
            type: "FeatureCollection",
            features: features
        };

        res.json(featureCollection);
    } catch (err) {
        console.error("Database read error:", err);
        res.status(500).json({ error: "Failed to load map data" });
    }
});

// POST /api/shapes (PROTECTED - Requires password to save)
app.post('/api/shapes', authenticate, async (req, res) => {
    const geojsonPayload = req.body;
    
    if (!geojsonPayload || !geojsonPayload.features) {
        return res.status(400).json({ error: "Invalid GeoJSON data" });
    }

    const client = await pool.connect();
    try {
        await client.query('BEGIN');
        
        // Replace existing features with the updated set
        await client.query('TRUNCATE TABLE map_shapes');

        const insertQuery = 'INSERT INTO map_shapes (geojson) VALUES ($1)';
        for (const feature of geojsonPayload.features) {
            await client.query(insertQuery, [feature]);
        }

        await client.query('COMMIT');
        res.json({ success: true, message: "Map shapes saved successfully!" });
    } catch (err) {
        await client.query('ROLLBACK');
        console.error("Database write error:", err);
        res.status(500).json({ error: "Failed to save map data" });
    } finally {
        client.release();
    }
});

// DELETE /api/shapes (PROTECTED - Requires password to clear map)
app.delete('/api/shapes', authenticate, async (req, res) => {
    try {
        await pool.query('TRUNCATE TABLE map_shapes');
        res.json({ success: true, message: "Map cleared successfully" });
    } catch (err) {
        console.error("Database delete error:", err);
        res.status(500).json({ error: "Failed to clear map" });
    }
});

// Block access to unmapped endpoints
app.use((req, res) => {
    res.status(404).send('Access Denied: Route not found.');
});

// Start Server
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`\n==================================================`);
    console.log(`🚀 Map Server is running!`);
    console.log(`🌐 Local URL:  http://localhost:${PORT}`);
    console.log(`==================================================\n`);
});