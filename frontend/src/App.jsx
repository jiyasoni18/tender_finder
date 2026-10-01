import React from "react";
import { BrowserRouter as Router, Routes, Route, NavLink } from "react-router-dom";
import Home from "./Home";
import TenderFinder from "./TenderFinder";
import SummaryCreation from "./SummaryCreation";
import DocCreation from "./DocCreation";
import "./App.css";

export default function App() {
  return (
    <Router>
      <div className="main-layout">
        <nav className="top-navbar">
          <div className="nav-logo">
            <span className="logo-icon">🏢</span> TenderFinder Pro
          </div>
          <div className="nav-links">
            <NavLink to="/" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"} end>
              🏠 Home
            </NavLink>
            <NavLink to="/finder" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              🔍 Tender Finder
            </NavLink>
            <NavLink to="/summary" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              📄 Summary Creation
            </NavLink>
            <NavLink to="/mapping" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
              📑 Doc Mapping
            </NavLink>
          </div>
        </nav>

        <div className="page-content">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/finder" element={<TenderFinder />} />
            <Route path="/summary" element={<SummaryCreation />} />
            <Route path="/mapping" element={<DocCreation />} />
          </Routes>
        </div>
      </div>
    </Router>
  );
}
