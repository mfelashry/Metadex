import { useEffect, useState } from "react";
import { formatBytes } from "./analyzeImage";

type FolderFile = { name: string; size: number; path: string };

type BatteryManager = { charging: boolean };

declare global {
  interface Navigator {
    getBattery?: () => Promise<BatteryManager>;
  }
}

const UNAVAILABLE = "not available on this computer";
const IMAGE_NAME = /\.(jpe?g|png|gif|webp|bmp|heic)$/i;

export function ComputerPanel() {
  const [files, setFiles] = useState<FolderFile[] | null>(null);
  const [folder, setFolder] = useState<string | null>(null);
  const [power, setPower] = useState(UNAVAILABLE);
  const [idle, setIdle] = useState(UNAVAILABLE);
  const [motion, setMotion] = useState(UNAVAILABLE);

  useEffect(() => {
    let stop = false;

    async function readStatus() {
      const getBattery = navigator.getBattery?.bind(navigator);
      if (!getBattery) {
        if (!stop) {
          setPower(UNAVAILABLE);
          setIdle(UNAVAILABLE);
        }
        return;
      }
      try {
        const battery = await getBattery();
        if (!stop) {
          setPower(battery.charging ? "Plugged in" : "On battery");
          setIdle(UNAVAILABLE);
        }
      } catch {
        if (!stop) {
          setPower(UNAVAILABLE);
          setIdle(UNAVAILABLE);
        }
      }
    }

    void readStatus();
    const timer = window.setInterval(() => void readStatus(), 5000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let sawSensor = false;
    let last: { x: number; y: number; z: number } | null = null;

    const onMotion = (event: DeviceMotionEvent) => {
      const acc = event.accelerationIncludingGravity;
      if (!acc || acc.x == null || acc.y == null) return;
      const next = { x: acc.x, y: acc.y, z: acc.z ?? 0 };
      if (Math.hypot(next.x, next.y, next.z) < 2) return;
      sawSensor = true;
      if (last) {
        const delta = Math.hypot(next.x - last.x, next.y - last.y, next.z - last.z);
        setMotion(delta > 1.2 ? "Moving" : "Still");
      } else {
        setMotion("Still");
      }
      last = next;
    };

    window.addEventListener("devicemotion", onMotion);
    const timer = window.setTimeout(() => {
      if (!sawSensor) setMotion(UNAVAILABLE);
    }, 1600);
    return () => {
      window.removeEventListener("devicemotion", onMotion);
      window.clearTimeout(timer);
    };
  }, []);

  async function chooseFolder() {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ".jpg,.jpeg,.png,.gif,.webp,.bmp,.heic,image/*";
    input.setAttribute("webkitdirectory", "");
    input.onchange = () => {
      const chosen = [...(input.files ?? [])].filter((file) => IMAGE_NAME.test(file.name));
      setFolder(null);
      setFiles(
        chosen.map((file) => ({
          name: file.name,
          size: file.size,
          path: file.webkitRelativePath || file.name,
        })),
      );
    };
    input.click();
  }

  return (
    <section className="computer-panel" aria-label="This computer">
      <h3>On this computer</h3>
      <p>Choose a folder to list images. Nothing is scanned until you do, and the files stay here.</p>
      <button type="button" onClick={() => void chooseFolder()}>
        Choose a folder
      </button>
      {folder && <p className="computer-note">{folder}</p>}
      {files && files.length === 0 && <p className="computer-note">No images in that folder.</p>}
      {files && files.length > 0 && (
        <ul className="computer-files">
          {files.map((file) => (
            <li key={file.path}>
              <strong>{file.name}</strong>
              <span>{formatBytes(file.size)}</span>
              <small>{file.path}</small>
            </li>
          ))}
        </ul>
      )}
      <dl className="computer-status">
        <div>
          <dt>Power</dt>
          <dd>{power}</dd>
        </div>
        <div>
          <dt>Activity</dt>
          <dd>{idle}</dd>
        </div>
        <div>
          <dt>Motion</dt>
          <dd>{motion}</dd>
        </div>
      </dl>
    </section>
  );
}
