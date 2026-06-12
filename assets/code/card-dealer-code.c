#pragma config(Sensor, S1,     leftDistance,   sensorEV3_Ultrasonic)
#pragma config(Sensor, S2,     rightDistance,  sensorEV3_IRSensor)
#pragma config(Sensor, S3,     color,          sensorEV3_Color)
#pragma config(Sensor, S4,     gyro,           sensorEV3_Gyro, modeEV3Gyro_RateAndAngle)
#pragma config(Motor,  motorA,          rotator,       tmotorEV3_Large, openLoop, reversed, encoder)
#pragma config(Motor,  motorB,          rightShuffler, tmotorEV3_Large, openLoop, reversed, encoder)
#pragma config(Motor,  motorC,          dealer,        tmotorEV3_Medium, PIDControl, encoder)
#pragma config(Motor,  motorD,          leftShuffler,  tmotorEV3_Large, openLoop, reversed, encoder)

// definition for motor port naming
#define leftDistance S1
#define rightDistance S2
#define color S3
#define gyro S4
#define rotator motorA
#define rightShuffler motorB
#define dealer motorC
#define leftShuffler motorD

// public values
const int LSDEFAULTDIS = 6; //Ultrasonic Sensor, picks up the center of the holder
const int RSDEFAULTDIS = 20; //Infrared Sensor
const int COLOURDEFAULTREAD = 14; //Reflected Light Mode

const int TICKSPEED = 20;
const int MAX_PLAYERS = 8;


// control functions
void ejectAll();
void waitLoad();
void turnAbsolute(int targetAngle);

bool shuffle();
bool dealSingle(bool isClose);

task jiggle();

// other functions
void getAngleArr(int* angleArray, int numPlayers);
void config();
int getScaledGyroDegrees();
void pause();
void clearDisplay();
bool dealPlayers(int* settings, int* angles);
bool dealDealer(int* settings);
bool playRound(int* settings, int* angles);

// start menu functions
void startMenu(int * settings);
int getDealerCount();
int getCardCount();
int getPlayerCount();
int getRoundCount();

//------------------------------------------------------------------------------------------------------------------------

// control functions

// returns adjusted gyro value for improved performance accuracy
int getScaledGyroDegrees(){
	const float GYRODRIFTSCALE = 0.98; //Tuning value
	// function adjusts for sensor error through a proportional scale factor
	// scale factor is estimated by turning the robot physically multiple times and determining the percent error

	return getGyroDegrees(gyro) / GYRODRIFTSCALE;
}

// PID based turn function
void turnAbsolute(int targetAngle){
		const int TURN_TOLERANCE = 2;

    int error = 0;
    int lastError = 0;
    int integral = 0;
    int derivative = 0;
    
    int motorPower = 0;

    const float Kp = 0.50; //tuned value
    const float Ki = 0.03; //tuned value
    const float Kd = 0.1; //tuned value

    const float maxPower = 50;
    const float minPower = 10; //minimum power that results in consistent motion

    while(true){
        int currentAngle = getScaledGyroDegrees();
        error = targetAngle - currentAngle;

        integral += error;
        derivative = error - lastError;

        motorPower = Kp * error + Ki * integral + Kd * derivative;

        //cap power at the max power
        if(motorPower > 100) motorPower = maxPower;
        if(motorPower < -100) motorPower = -maxPower;

        //ensure motor achieves at least the min power
        if(motorPower < 10 && motorPower > 0) motorPower = minPower;
        if(motorPower > -10 && motorPower < 0) motorPower = -minPower;

        motor[rotator] = motorPower;

        if(abs(error) <= TURN_TOLERANCE){
            motor[rotator] = 0;
            break;
        }

        lastError = error;
        wait1Msec(TICKSPEED);
    }
}

bool shuffle(){

	// ammount of time each side of the shuffler is on for
	int rsTime = 0;
	int lsTime = 0;

	// the min/max ammount of time each side can be on for
	// ensures proper randomization
	int minDelay = 1000;
	int maxDelay = 2000;

	// the ammount of cycles where no progress has been made
	// used to keep track of jams
	int stall = 0;

	// the distance from the cards to  ultrasonic sensor
	// keeps track of the progress (decreasing distance indicates cards are leaving the holder and being shuffled)
	int prevLSDistance = 0;
	int prevRSDistance = 0;

	bool isEmpty = false;
	// begins the jiggle task which shakes the bot decrease rate of jams, and for aesthetic purposes
	startTask(jiggle);
	
	while (!isEmpty){

		rsTime = rand() % (maxDelay - minDelay + 1) + minDelay;
		lsTime = rand() % (maxDelay - minDelay + 1) + minDelay;
		
		// if the sensor read that there are no more cards left in at least one chamber it will flush out the other chamber to speed up the process
		isEmpty =!(abs (SensorValue[leftDistance] - LSDEFAULTDIS) > 1 && abs (SensorValue[rightDistance] - RSDEFAULTDIS) > 4);
		
		if (isEmpty){
			// if right side is empty and left side is not empty, it will turn on only the left side until it is also empty
			if (abs (SensorValue[leftDistance] - LSDEFAULTDIS) > 1){
				motor[leftShuffler] = 100;
				while (abs (SensorValue[leftDistance] - LSDEFAULTDIS) > 1){}
			}
			else {
				motor[rightShuffler] = 100;
				while (abs(SensorValue[rightDistance] - RSDEFAULTDIS) > 4){}
			}
		}
		else{
			motor[rightShuffler] = 100;
			wait1Msec(rsTime);
			motor[rightShuffler] = -30;
			wait1Msec(600);
			motor[leftShuffler] = 100;
			motor[rightShuffler] = 0;

			motor[leftShuffler] = 100;
			wait1Msec(lsTime);

			motor[leftShuffler] = -30;
			wait1Msec(600);
			motor[rightShuffler] = 100;
			motor[leftShuffler] = 0;
		}

		//checks if any progress was made on the shuffler
		if (abs(SensorValue [leftDistance] - prevLSDistance) <= 1 && abs(SensorValue [rightDistance] - prevRSDistance) <= 2){
			stall++;
			} else {
			stall = 0;
		}
		// if the shuffler hasnt made progress in 5 cycles, it will return false and start the jam fixing process
		if (stall >= 5 ) {
			stopTask(jiggle);
			motor[dealer] = 0;
			motor[rotator] = 0;
			motor[rightShuffler] = 0;
			motor[leftShuffler] = 0;
			return false;
		}

		prevLSDistance = SensorValue[leftDistance];
		prevRSDistance = SensorValue[rightDistance];
	}

	stopTask(jiggle);
	motor[dealer] = 0;
	motor[rotator] = 0;

	// runs the shuffler for 2.5 sec to remove any strnded cards
	motor[rightShuffler] = 100;
	motor[leftShuffler] = 100;
	wait1Msec(2500);
	motor[rightShuffler] = 0;
	motor[leftShuffler] = 0;

	return true;
}

// waits for the cards to be placed in the shuffler chamber, and settled in before allowing anythign else to happen
void waitLoad(){
	
	int stableTime = 0;
	
	const int minMilliseconds = 2000;
	
	int prevRSDistance = 0;
	int prevLSDistance = 0;

	// checks if the card has been stable for at least 2000 millisecond
	while (stableTime < minMilliseconds){
		if (abs (SensorValue[leftDistance] - LSDEFAULTDIS) <= 1 || abs (SensorValue[rightDistance] - RSDEFAULTDIS) <= 4 ) {
			// if no cards are in the chamber keep the resetTime at 0 seconds
			stableTime = 0;
		}
		else if(SensorValue[leftDistance] == prevLSDistance && SensorValue[rightDistance] == prevRSDistance)
		{
			// if cards are in the chamber AND the sensors read a stable value (meaining the users hands are in the machine anymore)
			// increases the stable time
			stableTime += TICKSPEED;
		}
		else {
			// if cards are in chamber but hands are still in the machine, the robot must conitnue waiting
			stableTime = 0;
		}

		prevLSDistance = SensorValue[leftDistance];
		prevRSDistance = SensorValue[rightDistance];
		wait1Msec(TICKSPEED);
	}
}

// deals a single card
bool dealSingle(bool isClose)
{
	// cards dealt closer to the bot are at lower speeds and need a longer delay between due to the decreased velocity
	int speed = (isClose ? 40 : 100);
	int waitTime = (isClose ? 600 : 250);
	
	motor[dealer] = speed;
	
	// for 20 ticks of the robot tick speed checkks if a card exited the dealer
	for(int i=0; i<50;)
	{
		if(abs(SensorValue[color] - COLOURDEFAULTREAD) <1)
		{
			wait1Msec(TICKSPEED);
			i++;
		}
		else
		{
			wait1Msec(waitTime);
			motor[dealer] = - speed;
			wait1Msec(waitTime);
			motor[dealer] = 0;
			return true;
		}
	}
	
	// if no card exited the dealer when it was supposed to this returns false and thus begins the error fixing process
	motor[dealer] = 0;
	return false;
}

// turns the dealer on until no card exits (shoots the card out until no cards are left)
void ejectAll(){
	motor[dealer] = 40;
	for (int i = 0; i < 50;){
		if (abs(SensorValue[color] - COLOURDEFAULTREAD) < 1) i++;
		else i = 0;

		wait1Msec(TICKSPEED);
	}
	motor[dealer] = 0;
}

// begins a seperate thread that shakes the robot back and forth until it is stopped
// stops automatically after 10 seconds if not stopped seperately
task jiggle(){
	for (int i = 0; i < 10; i++){
		motor[rotator] = 80;
		wait1Msec(200);
		motor[rotator] = -80;
		wait1Msec(200);
		motor[rotator] = 0;
		wait1Msec(600);
	}
}

// --------------------------------------------------------
// other fucntions

// error handling function
void pause ()
{
	displayTextLine(4, "Robot has encountered an error.");
	displayTextLine(5, "Press ENTER to restart round.");

	// stops all motor motion and turns back to start pos
	stopTask(jiggle);

	turnAbsolute(0);
	motor[dealer] = 0;
	motor[rotator] = 0;
	motor[leftShuffler] = 0;
	motor[rightShuffler] = 0;

	ejectAll();

	//  allows the user to fix any error and waits for enter button to continue
	while(!getButtonPress(buttonEnter)) {}
	while(getButtonPress(buttonEnter)) {}

	clearDisplay();
}

// creates a STATIC array in memory which keeps track of the heading of each player so it where to turn to
// returns the pointer to the array so it can be accessed by different functions
void getAngleArr(int* angleArray, int numPlayers)
{
	int spacing = 180 /(numPlayers - 1);
	for(int i = 0; i < numPlayers; i++)
	{
		angleArray[i]= -90 + i * spacing;
	}
	return;
}

// process for playinh the round
// returns false if the round couldnt be played out (e.g card got jammed)
bool playRound(int* settings, int* angles){
	waitLoad();
	// if shuffler encountered an error, stops the round and begins error handling process
	if (!shuffle()) return false;
	wait1Msec(1000);
	
	// if dealer encountered an error, stops the round and begins error handling process
	if (!dealPlayers(settings, angles)) return false;
	wait1Msec(1000);
	
	// if dealer encountered an error, stops the round and begins error handling process
	if (!dealDealer(settings)) return false;
	wait1Msec(1000);
	
	// turns to the side to eject all the cards as to not get in anyones way
	turnAbsolute(135);
	ejectAll();
	turnAbsolute(0);
	return true;
}

// deals the cards given the settings and the array of player headings which are passed in as pointers
bool dealPlayers (int* settings, int* angles){
	int numPlayers = settings[1];
	int numCards = settings[2];
	int totalCards = numPlayers * numCards;

	int cardsArr[8] = {0,0,0,0,0,0,0,0};
	int cardsDealt = 0;

	turnAbsolute(0);
	while(cardsDealt < totalCards){
		// picks a random player to deal to
		int n = random(numPlayers - 1);
		// if player doesnt have the max number of cards deal them a card
		if (cardsArr[n] < numCards){
			turnAbsolute(angles[n]);
			
			// if there was an error dealing, return the dealPlayer function as false
			if(!dealSingle(false)) return false;

			cardsArr[n]++;
			cardsDealt++;
		}
	}
	return true;
}

bool dealDealer (int* settings){
	turnAbsolute(0);

	int numCards = settings[3];

	for (int i = 0; i < numCards; i++){
		
	// deals short to the dealer position
	// if there was error dealing return the dealDealer function as false, so the error handling process can start
		if (!dealSingle(true)) return false;
	}

	return true;
}

void config(){
	
	// limited resistance from these motors means coast can help prevent them from overheating
	motorType[leftShuffler] = motorCoast;
	motorType[rightShuffler] = motorCoast;
	motorType[dealer] = motorCoast;
	
	motorType[rotator] = motorBrake;
	
	SensorType [rightDistance] = sensorEV3_IRSensor;
 	wait1Msec (50);
 	SensorMode [rightDistance] = modeEV3IR_Calibration;
 	wait1Msec (50);
 	SensorMode [rightDistance] = modeEV3IR_Proximity;
 	wait1Msec (50);
 	
 	SensorType [leftDistance] = sensorEV3_Ultrasonic ;
 	wait1Msec (50);
 	SensorMode [leftDistance] = modeEV3Ultrasonic_Cm;
 	wait1Msec (50);
  	
	SensorType [color] = sensorEV3_Color ;
 	wait1Msec (50);
 	SensorMode[color] = modeEV3Color_Reflected;
 	wait1Msec (50);
 	
	SensorMode[gyro] = modeEV3Gyro_Calibration;
	wait1Msec (50);
 	SensorMode[gyro] = modeEV3Gyro_RateAndAngle;
 	wait1Msec (50);
	resetGyro(gyro);
}

bool shutDown()
{
	// stop all motors
	motor[rightShuffler] = 0;
	motor[leftShuffler] = 0;
	motor[rotator] = 0;
	motor[dealer] = 0;
	
	// turns back to start and ejects all cards
	turnAbsolute(0);
	ejectAll();

	// displays a thank you message
	displayTextLine(5, "Thank you for playing!");

	displayTextLine(10, "Would you like to play again?");
	displayTextLine(11, "Up for yes, Down for no");
	
	
	while(!getButtonPress(buttonUp) && !getButtonPress(buttonDown)) {}
	if(getButtonPress(buttonUp))
	{
		while(getButtonPress(buttonUp)){}	
		// returns false to indicate that the program will NOT shutdwon
		return false;
	}
	else
	{
		while(getButtonPress(buttonDown)){}
		//returns true to indicate that the program will shutdown
		return true;	
	}
}

void clearDisplay ()
{
	for (int i = 0; i<15; i++)
	{
		displayTextLine(i, "");
	}
}

//-----------------------------------------------------------------------------
// start menu
int getRoundCount ()
{
	// default number of rounds is 1
	int roundCount = 1;

	displayTextLine(4, "UP and DOWN to set # rounds.");
	displayTextLine(5, "Press ENTER to proceed.");
	
	while(!getButtonPress(buttonEnter))
	{
		displayTextLine(6, "%d", roundCount);

		while(!getButtonPress(buttonUp) && (!getButtonPress(buttonDown)))
		{
			if (getButtonPress(buttonEnter))
			{
				while(getButtonPress(buttonEnter)) {}
				return roundCount;
			}
		}
		if (getButtonPress(buttonUp))
		{
			while(getButtonPress(buttonUp)) {}
			roundCount++;
		}
		else if (getButtonPress(buttonDown))
		{
			while(getButtonPress(buttonDown)) {}
			// min number of rounds is 1
			if (roundCount > 1)
			{
				roundCount--;
			}
		}
		while(getButtonPress(buttonUp) || (getButtonPress(buttonDown)))	{}
		wait1Msec(TICKSPEED);
	}
	return roundCount;
}

int getPlayerCount ()
{
	// default num players is 2
	int playerCount = 2;
	
	displayTextLine(4, "UP and DOWN to set # players.");
	displayTextLine(5, "Press ENTER to proceed.");
		
	while (!getButtonPress(buttonEnter))
	{
		displayTextLine(6, "%d", playerCount);

		while(!getButtonPress(buttonUp) && (!getButtonPress(buttonDown)))
		{
			if (getButtonPress(buttonEnter))
			{
				while(getButtonPress(buttonEnter)) {}
				return playerCount;
			}
		}
		if (getButtonPress(buttonUp))
		{
			// max number of player is 8
			while(getButtonPress(buttonUp)) {}
			if (playerCount < MAX_PLAYERS)
			{
				playerCount++;
			}
		}
		else if (getButtonPress(buttonDown))
		{
			// min players is 2
			while(getButtonPress(buttonDown)) {}
			if (playerCount > 2)
			{
				playerCount--;
			}
		}
		wait1Msec(TICKSPEED);
	}
	return playerCount;
}

int getCardCount ()
{
	int cardCount = 1;
	
	displayTextLine(4, "UP and DOWN to set # cards/player.");
	displayTextLine(5, "Press ENTER to proceed.");
		
	while (!getButtonPress(buttonEnter))
	{
		
		displayTextLine(6, "%d", cardCount);

		while(!getButtonPress(buttonUp) && (!getButtonPress(buttonDown)))
		{
			if (getButtonPress(buttonEnter))
			{
				while(getButtonPress(buttonEnter)) {}
				return cardCount;
			}
		}
		if (getButtonPress(buttonUp))
		{
			while(getButtonPress(buttonUp)) {}
			cardCount++;
		}
		else
		{
			while(getButtonPress(buttonDown)) {}
			
			// min number of cards is at least 1
			if (cardCount > 1)
			{
				cardCount--;
			}
		}
		wait1Msec(TICKSPEED);
	}
	return cardCount;
}

int getDealerCount ()
{
	int dealerCount = 0;
	
	displayTextLine(4, "UP and DOWN to set # dealer cards.");
	displayTextLine(5, "Press ENTER to proceed.");
	
	while (!getButtonPress(buttonEnter))
	{
		
		displayTextLine(6, "%d", dealerCount);

		while(!getButtonPress(buttonUp) && (!getButtonPress(buttonDown)))
		{
			if (getButtonPress(buttonEnter))
			{
				while(getButtonPress(buttonEnter)) {}
				return dealerCount;
			}
		}
		if (getButtonPress(buttonUp))
		{
			while(getButtonPress(buttonUp)) {}
			dealerCount++;
		}
		else
		{
			while(getButtonPress(buttonDown)) {}
			// dealers cannot be dealt a negative number of cards
			if (dealerCount > 0)
			{
				dealerCount--;
			}
		}
		wait1Msec(TICKSPEED);
	}
	return dealerCount;
}

// returns the game array data as a pointer using a static array
void startMenu(int *settings)
{
	bool selection = false;

	displayTextLine(4, "Hello, esteemed guest!");
	displayTextLine(5, "This is a card dealer robot.");
	displayTextLine(6, "Press ENTER to begin");

	while(!getButtonPress(buttonEnter)) {}
	while(getButtonPress(buttonEnter)) {}

	while (!selection)
	{
		displayTextLine(5, "Selected Game: Poker.");
		displayTextLine(6, "Press ENTER button to play.");
		displayTextLine(7, "Cycle to next option using UP.");

		while(!getButtonPress(buttonEnter) && !getButtonPress(buttonUp)) {}
		if (getButtonPress(buttonEnter))
		{
			while(getButtonPress(buttonEnter)) {}
			settings[0] = 2;
			settings[2] = 2;
			settings[3] = 5;
			settings[1] = getPlayerCount();

			clearDisplay();

			return;
		}
		while(getButtonPress(buttonUp)) {}

		displayTextLine(5, "Selected Game: Custom.");
		displayTextLine(6, "Press ENTER button to play.");
		displayTextLine(7, "Cycle to next option using UP.");
		while(!getButtonPress(buttonEnter) && !getButtonPress(buttonUp)) {}
		if (getButtonPress(buttonEnter))
		{
			while(getButtonPress(buttonEnter)) {}

			settings[0] = getRoundCount();
			wait1Msec(TICKSPEED);

			settings[1] = getPlayerCount();
			wait1Msec(TICKSPEED);

			settings[2] = getCardCount();
			wait1Msec(TICKSPEED);

			settings[3] = getDealerCount();
			wait1Msec(TICKSPEED);

			selection = true;
		}
		while(getButtonPress(buttonUp)) {}
	}

	clearDisplay();

	return;
}

task main()
{
	config();
	
	bool playing = true;
	while(playing)
	{
		int settings[4] = {0,0,0,0};
		// passes the array in as a pointer and the values are directly changed
		// this is the improves memory management
		startMenu(settings);

		int angles[MAX_PLAYERS] = {0,0,0,0,0,0,0,0};
		getAngleArr(angles, settings[1]);
		
		int numRounds = settings[0];

		for (int i = 0; i < numRounds;){
		displayTextLine (5 ,"Round: %d", i+1);
			// passes in the arrays to the play round function
			if(playRound(settings, angles)){
				i++;
			}
			// if the round wasnt played properly, activate the error mode (pause) and dotn count the round
			else pause();
		}
		
		// if not shutting downn, keep playing, else set playing to false
		playing = (shutDown() ? false : true);
		clearDisplay();
	}
	// stops all task ONLY AFTER RUNNING A SEPERATE shut down function.
	stopAllTasks();
}