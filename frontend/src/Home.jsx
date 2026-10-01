import React, { useState, useEffect } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import { Activity, FileText, CheckCircle, AlertCircle } from "lucide-react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6"];

export default function Home() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/results`)
      .then(r => r.json())
      .then(d => {
        setData(d);
        setLoading(false);
      })
      .catch(e => {
        console.error(e);
        setLoading(false);
      });
  }, []);

  const total = data.length;
  const passed = data.filter(t => t.value && t.value !== "N/A" && t.value !== "?").length;
  const manualReview = total - passed;

  const sourceMap = data.reduce((acc, t) => {
    const src = t.source || "Unknown";
    acc[src] = (acc[src] || 0) + 1;
    return acc;
  }, {});
  
  const pieData = Object.keys(sourceMap).map(k => ({ name: k, value: sourceMap[k] }));

  const barData = [
    { name: "Passed", count: passed },
    { name: "Manual Review", count: manualReview }
  ];

  if (loading) {
    return <div className="loading-screen">Loading Dashboard...</div>;
  }

  return (
    <div className="home-dashboard">
      <div className="dashboard-header">
        <h1>Overview Dashboard</h1>
        <p>Live statistics of all analyzed and sourced tenders</p>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon" style={{background: "#e0e7ff", color: "#4f46e5"}}><Activity /></div>
          <div>
            <h3>Total Analyzed</h3>
            <div className="stat-value">{total}</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{background: "#dcfce7", color: "#16a34a"}}><CheckCircle /></div>
          <div>
            <h3>Passed Automatically</h3>
            <div className="stat-value">{passed}</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{background: "#fef3c7", color: "#d97706"}}><AlertCircle /></div>
          <div>
            <h3>Needs Manual Review</h3>
            <div className="stat-value">{manualReview}</div>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{background: "#f3e8ff", color: "#9333ea"}}><FileText /></div>
          <div>
            <h3>Sources Crawled</h3>
            <div className="stat-value">{Object.keys(sourceMap).length}</div>
          </div>
        </div>
      </div>

      <div className="charts-grid">
        <div className="chart-card">
          <h3>Tenders by Source</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={pieData} cx="50%" cy="50%" outerRadius={100} label dataKey="value">
                {pieData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h3>Tender Status</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={barData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
