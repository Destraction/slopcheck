export async function save(): Promise<void> {}

export function handler(): void {
  save();
}

const label: string = "a";
export const same = label as string;
