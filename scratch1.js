const REF_LON = 106.88178028, REF_LAT = -6.11260706;
const REF_UTM_X = 708241.531, REF_UTM_Y = 9323986.322;
const ROTATION_DEG = 53.83;

// I'll just use simple trig instead of proj4, assuming the original array is in UTM already.
// Wait, the original JS has a fallback:
const boundaryPointsUTM = [
    [708241.5, 9323986.3], 
    [708251.3, 9323992.8],
    [708248.8, 9323998.4],
    [708251.5, 9324000.3],
    [708244.4, 9324007.4],
    [708232.0, 9323998.0]
];

const angle = ROTATION_DEG * (Math.PI / 180);
const polygon = [];
let minRx = Infinity, maxRx = -Infinity, minRy = Infinity, maxRy = -Infinity;
for (const [uX, uY] of boundaryPointsUTM) {
    const dx = uX - REF_UTM_X, dy = uY - REF_UTM_Y;
    const rx = dx * Math.cos(angle) - dy * Math.sin(angle);
    const ry = dx * Math.sin(angle) + dy * Math.cos(angle);
    polygon.push({ x: rx, y: ry });
    minRx = Math.min(minRx, rx); maxRx = Math.max(maxRx, rx);
    minRy = Math.min(minRy, ry); maxRy = Math.max(maxRy, ry);
}

console.log("Rotated Polygon:", polygon.map(p => `(${p.x.toFixed(2)}, ${p.y.toFixed(2)})`));
console.log(`minRx: ${minRx.toFixed(2)}, maxRx: ${maxRx.toFixed(2)}`);
console.log(`minRy: ${minRy.toFixed(2)}, maxRy: ${maxRy.toFixed(2)}`);