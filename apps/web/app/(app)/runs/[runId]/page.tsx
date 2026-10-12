import { RunMonitorScreen } from "@/components/workflow-screens";
export default async function Page({params}:{params:Promise<{runId:string}>}){const{runId}=await params;return <RunMonitorScreen runId={runId}/>}
