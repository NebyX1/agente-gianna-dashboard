const BASE = (import.meta as unknown as {env:Record<string,string>}).env.VITE_RUNTIME_URL || "";
export {BASE};

export class RuntimeRequestError extends Error {
 constructor(public status:number){
  super(status===401?"No se pudo vincular esta consola con Gianna.":`No pude completar la acción (${status}).`);
 }
}

export async function request(path:string,body?:unknown,signal?:AbortSignal){
 const response=await fetch(BASE+path,{method:body===undefined?"GET":"POST",credentials:"include",headers:body===undefined?{}:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),signal});
 if(!response.ok)throw new RuntimeRequestError(response.status);
 return response.json();
}
