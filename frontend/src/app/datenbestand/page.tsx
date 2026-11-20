import { CollectorDashboard } from "../../collector/CollectorDashboard";
import { getDashboardData, type DashboardView } from "../../lib/collector-db";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const VIEWS: DashboardView[] = ["overview", "entities", "relationships", "records", "runs"];
type SearchParams = Promise<{ view?: string; q?: string; type?: string }>;

export default async function DataInventoryPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const view = VIEWS.includes(params.view as DashboardView) ? (params.view as DashboardView) : "overview";
  const search = typeof params.q === "string" ? params.q.slice(0, 120) : "";
  const entityType = typeof params.type === "string" ? params.type.slice(0, 50) : "";

  try {
    const data = await getDashboardData(view, search, entityType);
    return <CollectorDashboard data={data} error={null} view={view} search={search} entityType={entityType} />;
  } catch (error) {
    const message = error instanceof Error && error.message === "DATABASE_URL fehlt in der Projekt-.env."
      ? "DATABASE_URL fehlt. Hinterlege die Neon-Verbindung in der .env im Projektstamm."
      : "Verbindung nicht möglich. Prüfe DATABASE_URL und den Netzwerkzugriff des Frontend-Servers.";
    return <CollectorDashboard data={null} error={message} view={view} search={search} entityType={entityType} />;
  }
}
