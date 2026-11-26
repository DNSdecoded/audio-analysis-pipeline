declare module 'plotly.js-dist-min' {
  export interface PlotlyHTMLElement extends HTMLElement {
    on(event: string, handler: (...args: any[]) => void): void;
    removeAllListeners?(event?: string): void;
    data: any[];
    layout: any;
  }

  export function newPlot(
    root: HTMLElement | string,
    data: any[],
    layout?: any,
    config?: any,
  ): Promise<PlotlyHTMLElement>;

  export function react(
    root: HTMLElement | string,
    data: any[],
    layout?: any,
    config?: any,
  ): Promise<PlotlyHTMLElement>;

  export function purge(root: HTMLElement | string): void;
  export function downloadImage(
    root: HTMLElement | string,
    opts?: any,
  ): Promise<string>;
  export function toImage(
    root: HTMLElement | string,
    opts?: any,
  ): Promise<string>;

  const Plotly: {
    newPlot: typeof newPlot;
    react: typeof react;
    purge: typeof purge;
    downloadImage: typeof downloadImage;
    toImage: typeof toImage;
    Plots: any;
  };
  export default Plotly;
}
