import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "../src/App";
let audioCallbacks:{onConnected?:()=>void;onDisconnected?:()=>void;onServerMessage?:(message:Record<string,unknown>)=>void;onUserStartedSpeaking?:()=>void;onBotStartedSpeaking?:()=>void;onBotStoppedSpeaking?:()=>void;onError?:(error:unknown)=>void};
vi.mock("@pipecat-ai/client-js",()=>({PipecatClient:class {
 connected=false;
 constructor(options:{callbacks:typeof audioCallbacks}){audioCallbacks=options.callbacks;}
 async connect(){this.connected=true;audioCallbacks.onConnected?.();}
 async disconnect(){this.connected=false;audioCallbacks.onDisconnected?.();}
 enableMic(){}
}}));
vi.mock("@pipecat-ai/small-webrtc-transport",()=>({SmallWebRTCTransport:class {}}));
let stream:{onmessage:((message:{data:string})=>void)|null;onerror:(()=>void)|null;onopen:(()=>void)|null;close:()=>void};
const snapshot={state:"DORMANT",user:{id:2,name:"Operador",role:"operator"},draft:null,receipt:null,errors:[],audio_connected:false,generation_id:"g"};
beforeEach(()=>{
 class Events {onmessage=null;onerror=null;onopen=null;constructor(){stream=new Proxy(this,{});}close=vi.fn();}
 vi.stubGlobal("EventSource",Events);
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:true,json:async()=>snapshot}));
});
it("mantiene controles con nombres accesibles y usa el supervisor para el texto",async()=>{
 render(<App/>);
 expect(await screen.findByText("Operador")).toBeVisible();
 for(const name of ["Activar Gianna","Pausar conversación","Detener voz","Repetir","Apagar micrófono","Abrir tickets"]){expect(screen.getByRole("button",{name,exact:true})).toBeVisible();}
 fireEvent.change(screen.getByLabelText("Mensaje para Gianna"),{target:{value:"Gianna, registrá un pedido"}});
 fireEvent.click(screen.getByRole("button",{name:"Enviar a Gianna"}));
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith("/api/command",expect.objectContaining({method:"POST",credentials:"include",body:JSON.stringify({action:"text",text:"Gianna, registrá un pedido"})})));
});
it("quita la conversación anterior cuando pierde autenticación",async()=>{
 render(<App/>);await screen.findByText("Operador");
 const {act}=await import("@testing-library/react");
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"transcript",data:{text:"Contenido del actor anterior"}})}));
 expect(screen.getByText("Contenido del actor anterior")).toBeVisible();
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"state",data:{...snapshot,user:null,state:"AUTH_REQUIRED"}})}));
 expect(screen.queryByText("Contenido del actor anterior")).toBeNull();
});
it("inicia un pedido sólo con una acción explícita y no ofrece corregir sin borrador",async()=>{
 render(<App/>);await screen.findByText("Operador");
 expect(screen.getByRole("button",{name:"Corregir borrador"})).toBeDisabled();
 fireEvent.click(screen.getByRole("button",{name:"Nuevo ticket",exact:true}));
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith("/api/command",expect.objectContaining({body:JSON.stringify({action:"text",text:"Nuevo ticket"})})));
});
it("aceptar abrir un ticket no usa el control de envío",async()=>{
 render(<App/>);await screen.findByText("Operador");
 const {act}=await import("@testing-library/react");
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"state",data:{...snapshot,state:"INVITING",pending_request:"La impresora no imprime"}})}));
 expect(screen.getByText("La impresora no imprime")).toBeVisible();
 expect(screen.queryByRole("button",{name:"Confirmar y enviar"})).toBeNull();
 fireEvent.click(screen.getByRole("button",{name:"Abrir este ticket"}));
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith("/api/command",expect.objectContaining({body:JSON.stringify({action:"text",text:"Sí, registralo"})})));
});

it("vincula una consola nueva antes de abrir los eventos",async()=>{
 vi.mocked(fetch).mockResolvedValueOnce({ok:false,status:401} as Response);
 render(<App/>);await screen.findByText("Operador");
 expect(fetch).toHaveBeenCalledWith("/api/pair",expect.objectContaining({method:"POST",credentials:"include",body:"{}"}));
 expect(vi.mocked(fetch).mock.calls.map(call=>call[0])).toEqual(["/api/state","/api/pair","/api/state"]);
 expect(screen.queryByText(/Se perdió la conexión/)).toBeNull();
 expect(screen.getByRole("button",{name:"Activar Gianna"})).toBeEnabled();
});

it("muestra la conexión inicial sin fingir que están arrancando los motores",async()=>{
 vi.mocked(fetch).mockImplementation(()=>new Promise(()=>{}));
 render(<App/>);
 expect(screen.getByRole("heading",{name:"Conectando con Gianna"})).toBeVisible();
 expect(screen.queryByText("Preparando los motores locales")).toBeNull();
 expect(screen.getByRole("button",{name:"Activar Gianna"})).toBeDisabled();
});

it("recupera el stream y conserva el borrador sin repetir comandos",async()=>{
 const draft={id:"d",revision:3,owner:"agent",payload:{description:"La impresora no imprime"},tool:"tickets.create"};
 vi.mocked(fetch).mockResolvedValue({ok:true,json:async()=>({...snapshot,draft})} as Response);
 render(<App/>);await screen.findByText("Operador");
 const previous=stream;
 const {act}=await import("@testing-library/react");
 act(()=>previous.onerror?.());
 expect(screen.getByRole("heading",{name:"Reconectando con Gianna"})).toBeVisible();
 expect(screen.getByText("La impresora no imprime")).toBeVisible();
 expect(screen.getByRole("button",{name:"Descartar borrador"})).toBeDisabled();
 await waitFor(()=>expect(stream).not.toBe(previous),{timeout:2000});
 expect(previous.close).toHaveBeenCalled();
 expect(screen.queryByText(/Estoy recuperando la conexión/)).toBeNull();
 expect(screen.getByRole("button",{name:"Descartar borrador"})).toBeEnabled();
 expect(vi.mocked(fetch).mock.calls.every(call=>call[0]==="/api/state")).toBe(true);
});

it("se recupera automáticamente de una falla inicial de red",async()=>{
 vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
 render(<App/>);
 expect(await screen.findByRole("heading",{name:"Reconectando con Gianna"})).toBeVisible();
 expect(await screen.findByText("Operador",{},{timeout:2000})).toBeVisible();
 expect(screen.queryByText(/Estoy recuperando la conexión/)).toBeNull();
});

it("distingue el rechazo de vinculación de una pérdida de conexión",async()=>{
 vi.mocked(fetch).mockResolvedValueOnce({ok:false,status:401} as Response)
  .mockResolvedValueOnce({ok:false,status:403} as Response);
 render(<App/>);
 expect(await screen.findByRole("heading",{name:"Vinculando esta consola"})).toBeVisible();
 expect(screen.getByText(/No pude vincular esta consola/)).toBeVisible();
 expect(screen.getByRole("button",{name:"Activar Gianna"})).toBeDisabled();
 fireEvent.click(screen.getByRole("button",{name:"Reintentar conexión"}));
 expect(await screen.findByText("Operador")).toBeVisible();
 expect(screen.queryByText(/No pude vincular esta consola/)).toBeNull();
});

it("una segunda consola no marca como terminada la voz de otra ventana",async()=>{
 render(<App/>);await screen.findByText("Operador");
 const {act}=await import("@testing-library/react");
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"speech",data:{text:"Revisá el pedido",silent:false,utterance_id:"u",generation_id:"g"}})}));
 await new Promise(resolve=>setTimeout(resolve,250));
 expect(vi.mocked(fetch).mock.calls.some(call=>call[0]==="/api/playback-complete")).toBe(false);
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"speech",data:{text:"Modo silencioso",silent:true,utterance_id:"u2",generation_id:"g"}})}));
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith("/api/playback-complete",expect.objectContaining({body:JSON.stringify({utterance_id:"u2",generation_id:"g"})})));
});

it("reconecta al volver la red sin esperar el stream anterior",async()=>{
 render(<App/>);await screen.findByText("Operador");
 fireEvent(window,new Event("offline"));
 expect(screen.getByRole("heading",{name:"Reconectando con Gianna"})).toBeVisible();
 expect(screen.getByRole("button",{name:"Activar Gianna"})).toBeDisabled();
 fireEvent(window,new Event("online"));
 await waitFor(()=>expect(screen.getByRole("button",{name:"Activar Gianna"})).toBeEnabled());
 expect(screen.queryByRole("heading",{name:"Reconectando con Gianna"})).toBeNull();
});

it("no dice micrófono conectado hasta recibir audio por el canal real",async()=>{
 Object.defineProperty(navigator,"mediaDevices",{configurable:true,value:{enumerateDevices:async()=>[],removeEventListener:()=>{}}});
 render(<App/>);await screen.findByText("Operador");
 fireEvent.click(screen.getByRole("button",{name:"Conectar micrófono",exact:true}));
 expect(await screen.findByText("Comprobando que llegue audio del micrófono…")).toBeVisible();
 expect(screen.queryByRole("button",{name:"Micrófono conectado",exact:true})).toBeNull();
 const {act}=await import("@testing-library/react");
 act(()=>audioCallbacks.onServerMessage?.({kind:"audio_input",level:.06,received_ms:500}));
 expect(await screen.findByRole("button",{name:"Micrófono conectado",exact:true})).toBeVisible();
 expect(screen.getByText("Audio recibido · detecto sonido")).toBeVisible();
 expect(screen.getByRole("meter",{name:"Nivel de audio recibido"})).toHaveAttribute("value","0.72");
});

it("corta la reproducción al hablar y conserva el micrófono para la primera frase",async()=>{
 Object.defineProperty(navigator,"mediaDevices",{configurable:true,value:{enumerateDevices:async()=>[],removeEventListener:()=>{}}});
 const {container}=render(<App/>);await screen.findByText("Operador");
 fireEvent.click(screen.getByRole("button",{name:"Conectar micrófono",exact:true}));
 await screen.findByText("Comprobando que llegue audio del micrófono…");
 const {act}=await import("@testing-library/react");
 act(()=>audioCallbacks.onServerMessage?.({kind:"audio_input",level:.04,received_ms:500}));
 const audio=container.querySelector("audio")!;
 act(()=>{audioCallbacks.onServerMessage?.({kind:"speech",utterance_id:"old",generation_id:"g"});audioCallbacks.onBotStartedSpeaking?.();});
 expect(audio.muted).toBe(false);
 act(()=>{audioCallbacks.onUserStartedSpeaking?.();audioCallbacks.onBotStoppedSpeaking?.();});
 expect(audio.muted).toBe(true);
 expect(screen.getByRole("button",{name:"Micrófono conectado",exact:true})).toBeVisible();
 act(()=>{audioCallbacks.onServerMessage?.({kind:"speech",utterance_id:"new",generation_id:"g2"});audioCallbacks.onBotStartedSpeaking?.();});
 expect(audio.muted).toBe(false);
 expect(vi.mocked(fetch).mock.calls.some(call=>call[0]==="/api/playback-complete")).toBe(false);
});

it("un fallo de síntesis no muestra JSON ni pide reconectar un micrófono sano",async()=>{
 Object.defineProperty(navigator,"mediaDevices",{configurable:true,value:{enumerateDevices:async()=>[],removeEventListener:()=>{}}});
 render(<App/>);await screen.findByText("Operador");
 fireEvent.click(screen.getByRole("button",{name:"Conectar micrófono",exact:true}));
 await screen.findByText("Comprobando que llegue audio del micrófono…");
 const {act}=await import("@testing-library/react");
 act(()=>{audioCallbacks.onServerMessage?.({kind:"audio_input",level:.04,received_ms:500});audioCallbacks.onError?.({type:"error",data:{error:"TTS context test completed with no audio",fatal:false}});});
 expect(screen.queryByText(/TTS context/)).toBeNull();
 expect(screen.queryByText(/Reconectá el micrófono/)).toBeNull();
 expect(screen.getByRole("button",{name:"Micrófono conectado",exact:true})).toBeVisible();
});

it("ofrece reconectar si nunca llega el primer paquete de audio",async()=>{
 Object.defineProperty(navigator,"mediaDevices",{configurable:true,value:{enumerateDevices:async()=>[],removeEventListener:()=>{}}});
 render(<App/>);await screen.findByText("Operador");
 const {act}=await import("@testing-library/react");
 vi.useFakeTimers();
 try{
  await act(async()=>{fireEvent.click(screen.getByRole("button",{name:"Conectar micrófono",exact:true}));});
  expect(screen.getByText("Comprobando que llegue audio del micrófono…")).toBeVisible();
  act(()=>vi.advanceTimersByTime(5500));
  expect(screen.getByText(/No está llegando audio/)).toBeVisible();
  expect(screen.getByRole("button",{name:"Reconectar micrófono",exact:true})).toBeVisible();
 }finally{vi.useRealTimers();}
});


it("borra chat, borrador y mensaje sin cerrar la sesión",async()=>{
 vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>{});
 const draft={id:"d",revision:3,owner:"agent",payload:{description:"Borrador viejo"},tool:"tickets.create"};
 vi.mocked(fetch).mockResolvedValueOnce({ok:true,json:async()=>({...snapshot,draft})} as Response);
 render(<App/>);await screen.findByText("Operador");
 const {act}=await import("@testing-library/react");
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"transcript",data:{text:"Conversación anterior"}})}));
 fireEvent.change(screen.getByLabelText("Mensaje para Gianna"),{target:{value:"Texto sin enviar"}});
 fireEvent.click(screen.getByRole("button",{name:"Borrar conversación",exact:true}));
 await waitFor(()=>expect(fetch).toHaveBeenCalledWith("/api/command",expect.objectContaining({body:JSON.stringify({action:"reset_conversation"})})));
 await waitFor(()=>expect(screen.queryByText("Conversación anterior")).toBeNull());
 expect(screen.queryByText("Borrador viejo")).toBeNull();
 expect(screen.getByLabelText("Mensaje para Gianna")).toHaveValue("");
 expect(screen.getByText("Operador")).toBeVisible();
 expect(screen.getByRole("button",{name:"Nuevo ticket",exact:true})).toBeEnabled();
});

it("una consola observadora también se limpia con el evento de reinicio",async()=>{
 vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>{});
 render(<App/>);await screen.findByText("Operador");
 const {act}=await import("@testing-library/react");
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"speech",data:{text:"Respuesta anterior"}})}));
 fireEvent.change(screen.getByLabelText("Mensaje para Gianna"),{target:{value:"Texto anterior"}});
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"conversation_reset",data:snapshot})}));
 expect(screen.queryByText("Respuesta anterior")).toBeNull();
 expect(screen.getByLabelText("Mensaje para Gianna")).toHaveValue("");
});

it("no permite borrar mientras se guarda o comprueba una operación",async()=>{
 render(<App/>);await screen.findByText("Operador");
 const {act}=await import("@testing-library/react");
 for(const state of ["EXECUTING","RECONCILING"]){
  act(()=>stream.onmessage?.({data:JSON.stringify({kind:"state",data:{...snapshot,state}})}));
  expect(screen.getByRole("button",{name:"Borrar conversación",exact:true})).toBeDisabled();
 }
});

it("un comando que termina tarde no restaura el borrador después del reinicio",async()=>{
 vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>{});
 render(<App/>);await screen.findByText("Operador");
 let finish:(response:Response)=>void=()=>{};
 vi.mocked(fetch).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 fireEvent.change(screen.getByLabelText("Mensaje para Gianna"),{target:{value:"Pedido viejo"}});
 fireEvent.click(screen.getByRole("button",{name:"Enviar a Gianna",exact:true}));
 fireEvent.click(screen.getByRole("button",{name:"Borrar conversación",exact:true}));
 await waitFor(()=>expect(screen.getByRole("button",{name:"Borrar conversación",exact:true})).toBeEnabled());
 const {act}=await import("@testing-library/react");
 await act(async()=>{finish({ok:true,json:async()=>({...snapshot,draft:{id:"old",owner:"agent",revision:1,payload:{description:"Borrador viejo"}}})} as Response);});
 expect(screen.queryByText("Borrador viejo")).toBeNull();
});


it("el evento de borrado tardío no desconecta el micrófono ya reconectado",async()=>{
 vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>{});
 Object.defineProperty(navigator,"mediaDevices",{configurable:true,value:{enumerateDevices:async()=>[],removeEventListener:()=>{}}});
 render(<App/>);await screen.findByText("Operador");
 fireEvent.click(screen.getByRole("button",{name:"Conectar micrófono",exact:true}));
 await screen.findByText("Comprobando que llegue audio del micrófono…");
 const {act}=await import("@testing-library/react");
 act(()=>audioCallbacks.onServerMessage?.({kind:"audio_input",level:.04,received_ms:500}));
 const reset={...snapshot,generation_id:"clean-generation"};
 vi.mocked(fetch).mockResolvedValueOnce({ok:true,json:async()=>reset} as Response);
 fireEvent.click(screen.getByRole("button",{name:"Borrar conversación",exact:true}));
 await waitFor(()=>expect(screen.getByRole("button",{name:"Borrar conversación",exact:true})).toBeEnabled());
 act(()=>audioCallbacks.onServerMessage?.({kind:"audio_input",level:.04,received_ms:500}));
 await screen.findByRole("button",{name:"Micrófono conectado",exact:true});
 act(()=>stream.onmessage?.({data:JSON.stringify({kind:"conversation_reset",data:reset})}));
 expect(screen.getByRole("button",{name:"Micrófono conectado",exact:true})).toBeVisible();
});
