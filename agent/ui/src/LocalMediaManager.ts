import type { PipecatClientOptions, Tracks } from "@pipecat-ai/client-js";

/** Native microphone implementation of SmallWebRTC's public mediaManager contract.
 * Sends the captured microphone track directly, without an AudioContext in its
 * path. WebAudio suspension in an embedded/background browser cannot mute it.
 * App reconnects when changing devices. Incoming voice uses its audio element.
 */
export class LocalMediaManager {
  private options: PipecatClientOptions | null = null;
  private input: MediaStream | null = null;
  private enabled = true;
  private micId: string;
  private constraints: MediaTrackConstraints;
  readonly supportsScreenShare = false;

  constructor(constraints: MediaTrackConstraints = {}, micId = "") {
    this.constraints = constraints;
    this.micId = micId;
  }
  setClientOptions(options: PipecatClientOptions) {
    this.options = options;
    this.enabled = options.enableMic ?? true;
  }
  async initialize() {
    if (this.input) return;
    await this.acquire(this.micId);
    navigator.mediaDevices.addEventListener("devicechange", this.deviceChanged);
  }
  async connect() {
    await this.initialize();
  }
  async configure(constraints: MediaTrackConstraints) {
    this.constraints = constraints;
    const track = this.input?.getAudioTracks()[0];
    if (!track) throw new Error("No hay micrófono conectado.");
    await track.applyConstraints({...constraints,...(this.micId?{deviceId:{exact:this.micId}}:{})});
    return track.getSettings();
  }
  private async acquire(id: string) {
    // Permission/device errors propagate to connect; never report a usable microphone.
    const next = await navigator.mediaDevices.getUserMedia({
      video: false, audio: { ...this.constraints, ...(id ? { deviceId: { exact: id } } : {}) },
    });
    try {
      this.input?.getTracks().forEach(track => track.stop());
      this.input = next;
      this.micId = id;
      this.enableMic(this.enabled);
      this.options?.callbacks?.onTrackStarted?.(next.getAudioTracks()[0], { id: "local", name: "", local: true });
      await this.deviceChanged();
    } catch (error) {
      next.getTracks().forEach(track => track.stop());
      throw error;
    }
  }
  private deviceChanged = async () => {
    const devices = await navigator.mediaDevices.enumerateDevices();
    this.options?.callbacks?.onAvailableMicsUpdated?.(devices.filter(d => d.kind === "audioinput"));
    this.options?.callbacks?.onAvailableSpeakersUpdated?.(devices.filter(d => d.kind === "audiooutput"));
  };
  async disconnect() {
    navigator.mediaDevices.removeEventListener("devicechange", this.deviceChanged);
    this.input?.getTracks().forEach(track => track.stop());
    this.input = null;
  }
  async getAllMics() { return (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "audioinput"); }
  async getAllSpeakers() { return (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "audiooutput"); }
  async getAllCams() { return []; }
  async updateMic(id: string) { await this.acquire(id); }
  updateCam() { throw new Error("La cámara no está habilitada en Gianna."); }
  updateSpeaker() { /* App selects the sink of its actual remote audio element. */ }
  get selectedMic() { return { deviceId: this.input?.getAudioTracks()[0]?.getSettings().deviceId ?? this.micId }; }
  get selectedCam() { return {}; }
  get selectedSpeaker() { return {}; }
  enableMic(enabled: boolean) {
    this.enabled = enabled;
    this.input?.getAudioTracks().forEach(track => { track.enabled = enabled; });
  }
  enableCam(enabled: boolean) { if (enabled) this.updateCam(); }
  async enableScreenShare() { throw new Error("Compartir pantalla no está habilitado."); }
  get isMicEnabled() { return this.enabled; }
  get isCamEnabled() { return false; }
  get isSharingScreen() { return false; }
  tracks(): Tracks { return { local: { audio: this.input?.getAudioTracks()[0] } }; }
}
