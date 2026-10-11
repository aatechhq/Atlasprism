import { RunDetailScreen } from "@/components/screens";
export default async function Page({params}:{params:Promise<{runId:string}>}){const{runId}=await params;return <RunDetailScreen runId={runId}/>}
