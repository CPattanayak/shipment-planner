import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import PlanShipment from './pages/PlanShipment';
import ShipmentList from './pages/ShipmentList';
import ShipmentDetail from './pages/ShipmentDetail';
import AskAgent from './pages/AskAgent';
import Admin from './pages/Admin';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/"               element={<Navigate to="/plan" replace />} />
        <Route path="/plan"           element={<PlanShipment />} />
        <Route path="/shipments"      element={<ShipmentList />} />
        <Route path="/shipments/:id"  element={<ShipmentDetail />} />
        <Route path="/ask"            element={<AskAgent />} />
        <Route path="/admin"          element={<Admin />} />
      </Routes>
    </Layout>
  );
}
