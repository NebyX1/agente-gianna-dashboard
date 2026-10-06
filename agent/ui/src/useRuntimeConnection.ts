import {useEffect,useRef,useState} from "react";
import {BASE,request,RuntimeRequestError} from "./runtimeApi";

export type RuntimeEvent={kind:string;data:Record<string,unknown>};
type Connection="connecting"|"connected"|"reconnecting"|"unauthorized";

export function useRuntimeConnection<T>(onSnapshot:(snapshot:T)=>void,onEvent:(event:RuntimeEvent)=>void){
 const [connection,setConnection]=useState<Connection>("connecting");
 const [attempt,setAttempt]=useState(0);
 const handlers=useRef({onSnapshot,onEvent});
 useEffect(()=>{handlers.current={onSnapshot,onEvent};});
 useEffect(()=>{
  let stopped=false,connecting=false,stream:EventSource|null=null,timer:ReturnType<typeof setTimeout>|null=null,failures=0;
  const controller=new AbortController();
  const schedule=()=>{if(!stopped){if(timer)clearTimeout(timer);timer=setTimeout(()=>{timer=null;void connect();},Math.min(1000*2**failures++,8000));}};
  const connect=async()=>{
   if(stopped||connecting)return;
   connecting=true;
   try{
    let snapshot:T;
    try{snapshot=await request("/api/state",undefined,controller.signal);}
    catch(error){
     if(!(error instanceof RuntimeRequestError)||error.status!==401)throw error;
     await request("/api/pair",{},controller.signal);
     snapshot=await request("/api/state",undefined,controller.signal);
    }
    if(stopped)return;
    handlers.current.onSnapshot(snapshot);
    setConnection("connected");
    const currentStream=new EventSource(BASE+"/api/events",{withCredentials:true});
    stream=currentStream;
    currentStream.onopen=()=>{if(!stopped&&stream===currentStream){failures=0;setConnection("connected");}};
    currentStream.onmessage=message=>{
     if(stopped||stream!==currentStream)return;
     try{handlers.current.onEvent(JSON.parse(message.data) as RuntimeEvent);}catch{/* Ignore malformed events, preserving the current snapshot. */}
    };
    currentStream.onerror=()=>{
     if(stream!==currentStream)return;
     currentStream.close();stream=null;
     if(!stopped){setConnection("reconnecting");schedule();}
    };
   }catch(error){
    if(stopped)return;
    setConnection(error instanceof RuntimeRequestError&&[401,403].includes(error.status)?"unauthorized":"reconnecting");
    schedule();
   }finally{connecting=false;}
  };
  const offline=()=>{stream?.close();stream=null;if(!stopped){setConnection("reconnecting");schedule();}};
  const online=()=>{if(timer){clearTimeout(timer);timer=null;}if(!stream)void connect();};
  window.addEventListener("offline",offline);
  window.addEventListener("online",online);
  void connect();
  return()=>{stopped=true;controller.abort();stream?.close();if(timer)clearTimeout(timer);window.removeEventListener("offline",offline);window.removeEventListener("online",online);};
 },[attempt]);
 return {connection,retry:()=>setAttempt(value=>value+1)};
}
