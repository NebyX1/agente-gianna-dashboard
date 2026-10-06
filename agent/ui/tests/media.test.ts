import {expect,it,vi} from "vitest";
import {LocalMediaManager} from "../src/LocalMediaManager";

it("envía la pista física aunque WebAudio esté suspendido o no disponible",async()=>{
 const track={kind:"audio",enabled:true,stop:vi.fn(),getSettings:()=>({deviceId:"physical"}),applyConstraints:vi.fn()};
 const stream={getAudioTracks:()=>[track],getTracks:()=>[track]};
 const devices={getUserMedia:vi.fn().mockResolvedValue(stream),enumerateDevices:vi.fn().mockResolvedValue([]),addEventListener:vi.fn(),removeEventListener:vi.fn()};
 vi.stubGlobal("AudioContext",class{constructor(){throw Error("WebAudio blocked");}});
 Object.defineProperty(navigator,"mediaDevices",{configurable:true,value:devices});
 const manager=new LocalMediaManager({echoCancellation:true},"physical");
 await manager.connect();
 expect(manager.tracks().local.audio).toBe(track);
 expect(devices.getUserMedia).toHaveBeenCalledWith({video:false,audio:{echoCancellation:true,deviceId:{exact:"physical"}}});
 manager.enableMic(false);expect(track.enabled).toBe(false);
 manager.enableMic(true);expect(track.enabled).toBe(true);
 await manager.disconnect();expect(track.stop).toHaveBeenCalled();
 expect(manager.tracks().local.audio).toBeUndefined();
 vi.unstubAllGlobals();
});
