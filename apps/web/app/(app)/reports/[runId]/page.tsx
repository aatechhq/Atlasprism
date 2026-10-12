import { ReportWorkspaceScreen } from "@/components/workflow-screens";
export default async function Page({params}:{params:Promise<{runId:string}>}){const{runId}=await params;return <ReportWorkspaceScreen selectedRunId={runId}/>}
