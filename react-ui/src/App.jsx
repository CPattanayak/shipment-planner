import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import PlanShipment from './pages/PlanShipment';
import PlanShipmentV1 from './pages/PlanShipmentV1';
import PlanShipmentHybrid from './pages/PlanShipmentHybrid';
import AgentComparison from './pages/AgentComparison';
import ShipmentList from './pages/ShipmentList';
import ShipmentDetail from './pages/ShipmentDetail';
import AskAgent from './pages/AskAgent';
import Admin from './pages/Admin';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/"               element={<Navigate to="/compare" replace />} />
        <Route path="/compare"        element={<AgentComparison />} />
        <Route path="/plan/v1"        element={<PlanShipmentV1 />} />
        <Route path="/plan/v3"        element={<PlanShipment />} />
        <Route path="/plan/hybrid"    element={<PlanShipmentHybrid />} />
        {/* Legacy redirect */}
        <Route path="/plan"           element={<Navigate to="/plan/v3" replace />} />
        <Route path="/shipments"      element={<ShipmentList />} />
        <Route path="/shipments/:id"  element={<ShipmentDetail />} />
        <Route path="/ask"            element={<AskAgent />} />
        <Route path="/admin"          element={<Admin />} />
      </Routes>
    </Layout>
  );
}
