import { Navigate } from "react-router-dom";

/** @deprecated Use IntegrationsCatalog or SkillsCatalog directly. */
export default function SkillCatalog() {
  return <Navigate to="/integrations" replace />;
}
